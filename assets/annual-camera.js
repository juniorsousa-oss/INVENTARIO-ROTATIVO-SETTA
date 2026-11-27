export default function ({parentElement, setTriggerValue}) {
    const open = parentElement.querySelector("[data-open]");
    const close = parentElement.querySelector("[data-close]");
    const resume = parentElement.querySelector("[data-resume]");
    const photo = parentElement.querySelector("[data-photo]");
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
        resume.hidden = true;
        open.hidden = false;
    }
    function decode(source, width, height, maxSize) {
        const scale = Math.min(1, maxSize / Math.max(width, height));
        canvas.width = Math.round(width * scale);
        canvas.height = Math.round(height * scale);
        context.drawImage(source, 0, 0, canvas.width, canvas.height);
        const frame = context.getImageData(0, 0, canvas.width, canvas.height);
        return decodeQR(frame.data, frame.width, frame.height, {inversionAttempts: "attemptBoth"})?.data
            || SettaBarcode.decodeBarcode(frame);
    }
    function emit(raw) {
        const value = raw?.trim();
        if (!value) return false;
        if (value.length > 180 || !(value.includes(",") || /^[a-z0-9][a-z0-9_.-]{0,31}$/i.test(value))) {
            status.textContent = "O código lido não tem o formato de uma etiqueta.";
            return false;
        }
        stop();
        status.textContent = "Etiqueta lida. Confira os dados antes de adicionar.";
        setTriggerValue("scanned", value);
        return true;
    }
    function scan(run) {
        if (run !== generation) return;
        if (!host.getClientRects().length) { closeCamera(); return; }
        try {
            if (video.readyState >= 2 && video.videoWidth) {
                if (emit(decode(video, video.videoWidth, video.videoHeight, 1440))) return;
            }
        } catch {
            stop();
            status.textContent = "Não consegui processar a câmera. Bipe ou informe a etiqueta manualmente.";
            return;
        }
        timer = setTimeout(() => scan(run), 220);
    }
    function fromPhoto() {
        const file = photo?.files?.[0];
        if (!file) return;
        photo.value = "";
        stop();
        const run = generation;
        const url = URL.createObjectURL(file);
        const image = new Image();
        image.onload = () => {
            try {
                if (run === generation && !emit(decode(image, image.naturalWidth, image.naturalHeight, 1800))) {
                    status.textContent = "Não consegui ler a foto. Tente mais de perto e com melhor iluminação.";
                }
            } catch {
                if (run === generation) status.textContent = "Não consegui ler o arquivo da etiqueta.";
            } finally { URL.revokeObjectURL(url); }
        };
        image.onerror = () => {
            URL.revokeObjectURL(url);
            if (run === generation) status.textContent = "Não consegui abrir a foto da etiqueta.";
        };
        image.src = url;
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
                video: {facingMode: {ideal: "environment"}, width: {ideal: 1920}, height: {ideal: 1080}}
            });
            if (run !== generation || document.hidden || !host.getClientRects().length) {
                next.getTracks().forEach(track => track.stop());
                if (run === generation) stop();
                return;
            }
            stream = next;
            video.srcObject = next;
            video.hidden = false;
            await playVideo(run);
        } catch (error) {
            if (run !== generation) return;
            stop();
            status.textContent = error?.name === "NotAllowedError"
                ? "O navegador não liberou a câmera. Confira a permissão do site ou use o lançamento manual."
                : "Não consegui abrir a câmera. Você pode colar o código ou lançar manualmente.";
        }
    }
    async function playVideo(run) {
        try {
            await video.play();
        } catch (error) {
            if (run !== generation) return;
            if (error?.name === "NotAllowedError") {
                resume.hidden = false;
                status.textContent = "Toque em Iniciar prévia da câmera para continuar.";
                return;
            }
            throw error;
        }
        if (run !== generation) return;
        resume.hidden = true;
        status.textContent = "Aponte para o QR ou código de barras da etiqueta.";
        scan(run);
    }
    function resumeVideo() {
        if (!stream || resume.hidden) return;
        resume.hidden = true;
        const run = generation;
        playVideo(run).catch(() => {
            if (run !== generation) return;
            stop();
            status.textContent = "Não consegui iniciar o vídeo. Cole o código ou lance manualmente.";
        });
    }
    function closeCamera() {stop(); status.textContent = "";}
    function onVisibility() {if (document.hidden) closeCamera();}
    open.addEventListener("click", start);
    photo?.addEventListener("change", fromPhoto);
    close.addEventListener("click", closeCamera);
    resume.addEventListener("click", resumeVideo);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", closeCamera);
    return () => {
        closeCamera();
        open.removeEventListener("click", start);
        photo?.removeEventListener("change", fromPhoto);
        close.removeEventListener("click", closeCamera);
        resume.removeEventListener("click", resumeVideo);
        document.removeEventListener("visibilitychange", onVisibility);
        window.removeEventListener("pagehide", closeCamera);
    };
}
