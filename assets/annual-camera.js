export default function ({parentElement, setTriggerValue}) {
    const open = parentElement.querySelector("[data-open]");
    const close = parentElement.querySelector("[data-close]");
    const video = parentElement.querySelector("video");
    const status = parentElement.querySelector("[role=status]");
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d", {willReadFrequently: true});
    const host = parentElement.host || parentElement;
    let stream = null, timer = null, generation = 0;
    video.muted = true;

    function stop() {
        generation++;
        clearTimeout(timer);
        stream?.getTracks().forEach(track => track.stop());
        stream = null;
        video.pause();
        video.srcObject = null;
        video.hidden = true;
        close.hidden = true;
        open.hidden = false;
    }
    function scan(run) {
        if (run !== generation) return;
        if (!host.getClientRects().length) { closeCamera(); return; }
        try {
            if (video.readyState >= 2 && video.videoWidth) {
                const scale = Math.min(1, 960 / Math.max(video.videoWidth, video.videoHeight));
                canvas.width = Math.round(video.videoWidth * scale);
                canvas.height = Math.round(video.videoHeight * scale);
                context.drawImage(video, 0, 0, canvas.width, canvas.height);
                const frame = context.getImageData(0, 0, canvas.width, canvas.height);
                const value = decodeQR(frame.data, frame.width, frame.height, {inversionAttempts: "dontInvert"})?.data;
                if (value) {
                    if (value.length > 180 || !value.includes(",")) {
                        status.textContent = "Este QR não parece ser de uma etiqueta do inventário. Aponte para outra etiqueta.";
                    } else {
                        stop();
                        status.textContent = "QR lido. Confira os dados antes de adicionar.";
                        setTriggerValue("scanned", value);
                        return;
                    }
                }
            }
        } catch {
            stop();
            status.textContent = "Não consegui processar a câmera. Você pode colar o código ou lançar manualmente.";
            return;
        }
        timer = setTimeout(() => scan(run), 160);
    }
    async function start() {
        stop();
        const run = generation;
        if (!navigator.mediaDevices?.getUserMedia || !context) {
            status.textContent = "Câmera indisponível neste navegador. Use o Safari com HTTPS, cole o código ou lance manualmente.";
            return;
        }
        open.hidden = true;
        close.hidden = false;
        status.textContent = "Aguardando acesso à câmera…";
        try {
            const next = await navigator.mediaDevices.getUserMedia({
                audio: false,
                video: {facingMode: {ideal: "environment"}, width: {ideal: 1280}, height: {ideal: 720}}
            });
            if (run !== generation || document.hidden || !host.getClientRects().length) {
                next.getTracks().forEach(track => track.stop());
                if (run === generation) stop();
                return;
            }
            stream = next;
            video.srcObject = next;
            video.hidden = false;
            await video.play();
            if (run !== generation) return;
            status.textContent = "Aponte para o QR da etiqueta. A leitura é automática.";
            scan(run);
        } catch (error) {
            if (run !== generation) return;
            stop();
            status.textContent = error?.name === "NotAllowedError"
                ? "O navegador não liberou a câmera. Confira a permissão do site ou use o lançamento manual."
                : "Não consegui abrir a câmera. Você pode colar o código ou lançar manualmente.";
        }
    }
    function closeCamera() {stop(); status.textContent = "";}
    function onVisibility() {if (document.hidden) closeCamera();}
    open.addEventListener("click", start);
    close.addEventListener("click", closeCamera);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", closeCamera);
    return () => {
        closeCamera();
        open.removeEventListener("click", start);
        close.removeEventListener("click", closeCamera);
        document.removeEventListener("visibilitychange", onVisibility);
        window.removeEventListener("pagehide", closeCamera);
    };
}
