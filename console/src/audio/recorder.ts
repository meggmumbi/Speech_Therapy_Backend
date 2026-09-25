/**
 * Record from the microphone and hand back 16 kHz mono PCM WAV.
 *
 * MediaRecorder produces whatever the browser likes -- usually Opus in WebM
 * at 48 kHz. The server would accept that and resample it, but decoding here
 * means the console can play the exact bytes it is about to upload, so what
 * the researcher checks is what the participant will hear.
 */

export const TARGET_SR = 16_000;

export class Recorder {
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private stream: MediaStream | null = null;

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream);
    this.recorder.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.recorder.start();
  }

  /** Stop, decode, resample, and return WAV bytes ready to upload. */
  async stop(): Promise<Blob> {
    const rec = this.recorder;
    if (!rec) throw new Error("not recording");
    const done = new Promise<void>((resolve) => { rec.onstop = () => resolve(); });
    rec.stop();
    await done;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.recorder = null;
    this.stream = null;
    const raw = new Blob(this.chunks, { type: rec.mimeType });
    return encodeWav(await toMono16k(raw));
  }

  get active(): boolean { return this.recorder !== null; }
}

async function toMono16k(blob: Blob): Promise<Float32Array> {
  const ctx = new AudioContext();
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    const frames = Math.ceil(decoded.duration * TARGET_SR);
    const offline = new OfflineAudioContext(1, frames, TARGET_SR);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    const rendered = await offline.startRendering();
    return rendered.getChannelData(0).slice();
  } finally {
    await ctx.close();
  }
}

function encodeWav(samples: Float32Array): Blob {
  const bytesPerSample = 2;
  const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
  const view = new DataView(buffer);
  const write = (offset: number, text: string) => { for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i)); };
  write(0, "RIFF");
  view.setUint32(4, 36 + samples.length * bytesPerSample, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);              // PCM
  view.setUint16(22, 1, true);              // mono
  view.setUint32(24, TARGET_SR, true);
  view.setUint32(28, TARGET_SR * bytesPerSample, true);
  view.setUint16(32, bytesPerSample, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, samples.length * bytesPerSample, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}
