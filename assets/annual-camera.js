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
    let startedAt = 0, frames = 0, incompatible = false;
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
    function decode(source, width, height, maxSize, crop = false) {
        const w = crop ? Math.floor(width * .62) : width;
        const h = crop ? Math.floor(height * .62) : height;
        const scale = Math.min(1, maxSize / Math.max(w, h));
        canvas.width = Math.round(w * scale);
        canvas.height = Math.round(h * scale);
        if (crop) context.drawImage(source, (width-w)/2, (height-h)/2, w, h, 0, 0, canvas.width, canvas.height);
        else context.drawImage(source, 0, 0, canvas.width, canvas.height);
        const frame = context.getImageData(0, 0, canvas.width, canvas.height);
        return decodeQR(frame.data, frame.width, frame.height, {inversionAttempts: "attemptBoth"})?.data
            || (crop ? null : SettaBarcode.decodeBarcode(frame));
    }
    function emit(raw) {
        const value = typeof raw === "string" ? raw.trim() : "";
        if (!value) return false;
        if (value.length > 180 || !(value.includes(",") || /^[a-z0-9][a-z0-9_.-]{0,31}$/i.test(value))) {
            incompatible = true;
            status.textContent = "Código reconhecido, mas o formato não é aceito. Tente bipar ou lançar manualmente.";
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
                const {videoWidth: w, videoHeight: h} = video;
                if (emit(decode(video, w, h, 1440))) return;
                // Alternate a central, full-detail QR pass to keep small labels
                // readable without decoding the full 1080p frame on every tick.
                if (++frames % 3 === 0 && w > 700 && h > 400 && emit(decode(video, w, h, 1440, true))) return;
                if (!incompatible && Date.now() - startedAt > 5500) {
                    status.textContent = "Ainda não li a etiqueta. Centralize o código, ajuste a distância e evite reflexo.";
                }
            } else if (Date.now() - startedAt > 5500) {
                status.textContent = "A câmera não enviou imagem. Feche e abra a câmera ou tente uma foto.";
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
            try {
                const track = next.getVideoTracks?.()[0];
                if (track?.getCapabilities?.().focusMode?.includes("continuous") && track.applyConstraints) {
                    track.applyConstraints({advanced: [{focusMode: "continuous"}]}).catch(() => {});
                }
            } catch { /* Browser or device does not expose focus controls. */ }
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
        status.textContent = "Centralize a etiqueta. A leitura é automática.";
        startedAt = Date.now();
        frames = 0;
        incompatible = false;
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
