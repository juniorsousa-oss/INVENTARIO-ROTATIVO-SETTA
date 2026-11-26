import {readFileSync} from "node:fs";
import assert from "node:assert/strict";
import {test} from "node:test";
import vm from "node:vm";

const scanner = readFileSync(new URL("../assets/annual-camera.js", import.meta.url), "utf8");
const vendored = readFileSync(new URL("../assets/jsqr-1.4.0.js", import.meta.url), "utf8");

function fixture(getUserMedia, role = "00000001,000101,3") {
    const open = new EventTarget(), close = new EventTarget();
    const video = {readyState: 2, videoWidth: 32, videoHeight: 32, play: async () => {}, pause: () => {}};
    const status = {textContent: ""};
    const parent = { getClientRects: () => [1], querySelector:
        selector => ({"[data-open]":open, "[data-close]":close, video, "[role=status]":status})[selector] };
    const doc = new EventTarget();
    doc.createElement = () => ({getContext: () => ({drawImage() {}, getImageData: () => ({data: [], width: 32, height: 32})})});
    const window = new EventTarget(), outputs = [];
    const init = vm.runInNewContext("(" + scanner.replace("export default ", "") + ")", {
        navigator: {mediaDevices: {getUserMedia}}, window, document: doc, setTimeout, clearTimeout,
        decodeQR: () => ({data: role}),
    });
    const dispose = init({parentElement:parent, setTriggerValue: (...args) => outputs.push(args)});
    return {open, close, video, status, outputs, doc, dispose};
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
