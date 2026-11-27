import {readFileSync} from "node:fs";
import assert from "node:assert/strict";
import {test} from "node:test";
import vm from "node:vm";

const scanner = readFileSync(new URL("../assets/annual-camera.js", import.meta.url), "utf8");
const vendored = readFileSync(new URL("../assets/jsqr-1.4.0.js", import.meta.url), "utf8");

function fixture(getUserMedia, role = "00000001,000101,3", overrides = {}) {
    const open = new EventTarget(), close = new EventTarget(), resume = new EventTarget();
    const video = {readyState: 2, videoWidth: 32, videoHeight: 32, play: async () => {}, pause: () => {}};
    const status = {textContent: ""};
    const parent = { getClientRects: () => [1], querySelector:
        selector => ({"[data-open]":open, "[data-close]":close, "[data-resume]":resume, video, "[role=status]":status})[selector] };
    const doc = new EventTarget();
    doc.createElement = () => ({getContext: () => ({drawImage() {}, getImageData: () => ({data: [], width: 32, height: 32})})});
    const window = new EventTarget(), outputs = [];
    const init = vm.runInNewContext("(" + scanner.replace("export default ", "") + ")", {
        navigator: {mediaDevices: {getUserMedia}}, window, document: doc, setTimeout, clearTimeout,
        decodeQR: () => ({data: role}),
        SettaBarcode: {decodeBarcode: () => null},
        ...overrides,
    });
    const dispose = init({parentElement:parent, setTriggerValue: (...args) => outputs.push(args)});
    return {open, close, resume, video, status, outputs, doc, dispose};
}

function trackFixture() {
    const tracks = {stops:0};
    tracks.stream = {getTracks: () => [{stop: () => tracks.stops++}]};
    return tracks;
}
const click = control => control.dispatchEvent(new Event("click"));
const flush = () => new Promise(resolve => setImmediate(resolve));

test("vendored decoder is available without external requests or globals", () => {
    const env = {};
    assert.equal(vm.runInNewContext(vendored + "\ntypeof decodeQR", env), "function");
    assert.equal(env.jsQR, undefined);
});

test("starts only on tap, requests rear camera without audio, emits once and releases tracks", async () => {
    const tracks = trackFixture(), calls = [];
    const fx = fixture(async request => { calls.push(request); return tracks.stream; });
    assert.equal(calls.length, 0);
    click(fx.open);
    await flush();
    assert.equal(calls[0].audio, false);
    assert.equal(calls[0].video.facingMode.ideal, "environment");
    assert.deepEqual(fx.outputs, [["scanned", "00000001,000101,3"]]);
    assert.equal(tracks.stops, 1);
    assert.equal(fx.video.srcObject, null);
    fx.dispose();
    assert.equal(tracks.stops, 1);
});

test("permission rejection leaves camera off and no scan event", async () => {
    const fx = fixture(async () => { throw new DOMException("", "NotAllowedError"); });
    click(fx.open);
    await flush();
    assert.match(fx.status.textContent, /não liberou a câmera/);
    assert.deepEqual(fx.outputs, []);
    assert.equal(fx.open.hidden, false);
    fx.dispose();
});

test("unmount during a pending permission prompt releases a late camera stream", async () => {
    const tracks = trackFixture();
    let grant;
    const fx = fixture(() => new Promise(resolve => { grant = resolve; }));
    click(fx.open);
    fx.dispose();
    grant(tracks.stream);
    await flush();
    assert.equal(tracks.stops, 1);
    assert.deepEqual(fx.outputs, []);
});


test("offers a new tap if the browser postpones playing an authorized stream", async () => {
    const tracks = trackFixture();
    const fx = fixture(async () => tracks.stream);
    fx.video.play = async () => { throw new DOMException("", "NotAllowedError"); };
    click(fx.open);
    await flush();
    assert.equal(fx.resume.hidden, false);
    assert.equal(tracks.stops, 0);
    fx.video.play = async () => {};
    click(fx.resume);
    await flush();
    assert.deepEqual(fx.outputs, [["scanned", "00000001,000101,3"]]);
    assert.equal(tracks.stops, 1);
    fx.dispose();
});

test("bundled reader decodes a real EAN-13 image without network calls", () => {
    const lib = readFileSync(new URL("../assets/zxing-barcode-0.22.0.js", import.meta.url), "utf8");
    const decode = vm.runInNewContext(lib + "\nSettaBarcode.decodeBarcode");
    const L = ["0001101","0011001","0010011","0111101","0100011","0110001","0101111","0111011","0110111","0001011"];
    // EAN-13 leading 0 means LLLLLL; last digit is the checksum.
    const ean = "0123456789012";
    const barPattern = "000000000000101" + [...ean.slice(1,7)].map(c=>L[c]).join("") + "01010"
      + [...ean.slice(7)].map(c=>L[c].replace(/[01]/g, v=>v==="0" ? "1":"0")).join("") + "101000000000000";
    const scale = 4, height = 96, width = barPattern.length * scale;
    const data = new Uint8ClampedArray(width * height * 4);
    for (let y=0;y<height;y++) for (let x=0;x<width;x++) {
       const i=(y*width+x)*4, v=barPattern[Math.floor(x/scale)]==="1" ? 0:255;
       data[i]=data[i+1]=data[i+2]=v; data[i+3]=255;
    }
    assert.equal(decode({data,width,height}), ean);
});

test("undecodable live frames keep the camera active and show guidance", async () => {
    const tracks = trackFixture(), ticks = [];
    let time = 1000;
    const fx = fixture(async () => tracks.stream, null, {
        Date: {now: () => time},
        setTimeout: fn => { ticks.push(fn); },
    });
    fx.video.videoWidth = 1280;
    fx.video.videoHeight = 720;
    click(fx.open);
    await flush();
    for (let i = 0; i < 4; i++) {
        time += 1600;
        ticks.shift()();
    }
    assert.match(fx.status.textContent, /Ainda não li a etiqueta/);
    assert.equal(tracks.stops, 0);
    assert.deepEqual(fx.outputs, []);
    fx.dispose();
});
