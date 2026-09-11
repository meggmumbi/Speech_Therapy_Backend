"""Acoustic backends: raw audio in, per-frame phone posteriors out.

This is the module the original pipeline had no equivalent of. Everything else
in the package is arithmetic on the emission matrix produced here.

The backend sits behind :class:`AcousticModel` so that the model, the runtime
(PyTorch or ONNX Runtime) and the device are configuration rather than
structure. On the study laptop that means base-size ONNX INT8 on CPU; moving to
a rented GPU for the study window is a config change, not a rewrite.

Whatever model is chosen must expose a *phone* inventory. A character-CTC model
such as ``wav2vec2-base-960h`` cannot support GOP at all, so
:meth:`AcousticModel.describe` reports the inventory and
:func:`assert_phone_level` refuses to proceed with a character model.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np

from .config import PipelineConfig
from .features import ARPABET_PHONES

log = logging.getLogger(__name__)

# Tokens that are structural rather than phonetic in a CTC vocabulary.
_SPECIAL_TOKENS = {"<pad>", "<s>", "</s>", "<unk>", "|", "", " ", "[PAD]", "[UNK]"}

# Minimal IPA -> ARPAbet mapping, for models (such as the espeak-trained ones)
# whose labels are IPA. Covers the English inventory only; anything unmapped is
# dropped from the scoring inventory rather than guessed at.
ARPABET_FROM_IPA: dict[str, str] = {
    "p": "P", "b": "B", "t": "T", "d": "D", "k": "K", "ɡ": "G", "g": "G",
    "tʃ": "CH", "dʒ": "JH", "f": "F", "v": "V", "θ": "TH", "ð": "DH",
    "s": "S", "z": "Z", "ʃ": "SH", "ʒ": "ZH", "h": "HH",
    "m": "M", "n": "N", "ŋ": "NG", "l": "L", "ɹ": "R", "r": "R",
    "w": "W", "j": "Y",
    "i": "IY", "iː": "IY", "ɪ": "IH", "eɪ": "EY", "ɛ": "EH", "æ": "AE",
    "ɑ": "AA", "ɑː": "AA", "ɔ": "AO", "ɔː": "AO", "oʊ": "OW", "əʊ": "OW",
    "ʊ": "UH", "u": "UW", "uː": "UW", "ʌ": "AH", "ə": "AH",
    "ɚ": "ER", "ɝ": "ER", "ɜː": "ER", "aɪ": "AY", "aʊ": "AW", "ɔɪ": "OY",
}


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    backend: str
    device: str
    n_labels: int
    inventory: tuple[str, ...]
    frame_stride_s: float

    @property
    def is_phone_level(self) -> bool:
        """True when the label set looks like phones rather than letters."""
        known = sum(1 for p in self.inventory if p in ARPABET_PHONES)
        return known >= 20


@dataclass(frozen=True)
class Emissions:
    """Log-softmax emissions plus everything needed to interpret them."""

    log_probs: np.ndarray            # (T, V) float32/float64, log domain
    phone_to_id: dict[str, int]
    id_to_phone: dict[int, str]
    blank_id: int
    frame_stride_s: float
    inference_ms: float = 0.0

    @property
    def n_frames(self) -> int:
        return int(self.log_probs.shape[0])

    @property
    def duration_s(self) -> float:
        return self.n_frames * self.frame_stride_s


class AcousticModel(Protocol):
    def emissions(self, waveform: np.ndarray, sample_rate: int) -> Emissions: ...
    def describe(self) -> ModelInfo: ...
    def warmup(self) -> None: ...


def assert_phone_level(model: AcousticModel) -> None:
    """Refuse to score with a model that has no phone inventory."""
    info = model.describe()
    if not info.is_phone_level:
        raise ValueError(
            f"{info.model_id!r} exposes {info.n_labels} labels that do not look "
            "like phones. GOP scoring needs phone posteriors; a character-CTC "
            "model can only provide word-level alignment."
        )


def _normalise_vocab(raw_vocab: dict[str, int]) -> tuple[dict[str, int], dict[int, str]]:
    """Map a model's own labels onto ARPAbet, dropping what cannot be mapped.

    Unmappable labels keep their ids (the emission matrix is untouched) but are
    absent from the returned maps, so they can still win ``argmax`` and depress
    a GOP score -- they simply cannot be *named* in feedback. Silently
    renaming them would be worse.
    """
    phone_to_id: dict[str, int] = {}
    id_to_phone: dict[int, str] = {}
    for label, idx in raw_vocab.items():
        if label in _SPECIAL_TOKENS:
            continue
        stripped = label.strip().lstrip("ˈˌ")
        candidate = stripped.upper() if stripped.upper() in ARPABET_PHONES else \
            ARPABET_FROM_IPA.get(stripped)
        if candidate is None:
            continue
        # First id wins when several labels map to the same ARPAbet phone.
        phone_to_id.setdefault(candidate, idx)
        id_to_phone[idx] = candidate
    return phone_to_id, id_to_phone


class HFCTCAcousticModel:
    """PyTorch backend over any HuggingFace ``*ForCTC`` phone model."""

    def __init__(self, model_id: str, device: str = "cpu",
                 frame_stride_s: float = 0.02, num_threads: int | None = None):
        import torch
        from transformers import AutoModelForCTC, AutoProcessor

        if num_threads:
            torch.set_num_threads(num_threads)
        self._torch = torch
        self._model_id = model_id
        self._device = device
        self._frame_stride_s = frame_stride_s
        self._processor = AutoProcessor.from_pretrained(model_id)
        self._model = AutoModelForCTC.from_pretrained(model_id).to(device).eval()

        raw_vocab = self._processor.tokenizer.get_vocab()
        self.phone_to_id, self.id_to_phone = _normalise_vocab(raw_vocab)
        self.blank_id = getattr(self._processor.tokenizer, "pad_token_id", 0) or 0

    def describe(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._model_id, backend="torch", device=self._device,
            n_labels=int(self._model.config.vocab_size),
            inventory=tuple(sorted(self.phone_to_id)),
            frame_stride_s=self._frame_stride_s,
        )

    def warmup(self) -> None:
        """Run one throwaway inference so the first real request is not slow.

        Lazy init, allocator warm-up and any kernel autotuning all land on the
        first forward pass. Call this at server start; otherwise the first
        participant of every session pays several hundred extra milliseconds.
        """
        self.emissions(np.zeros(8000, dtype=np.float32), 16_000)

    def emissions(self, waveform: np.ndarray, sample_rate: int) -> Emissions:
        torch = self._torch
        started = time.perf_counter()
        inputs = self._processor(
            waveform, sampling_rate=sample_rate, return_tensors="pt",
        )
        with torch.inference_mode():
            logits = self._model(
                inputs.input_values.to(self._device)
            ).logits.squeeze(0)
            log_probs = torch.log_softmax(logits, dim=-1).cpu().numpy()
        return Emissions(
            log_probs=log_probs.astype(np.float64),
            phone_to_id=self.phone_to_id, id_to_phone=self.id_to_phone,
            blank_id=self.blank_id, frame_stride_s=self._frame_stride_s,
            inference_ms=(time.perf_counter() - started) * 1000.0,
        )


class OnnxCTCAcousticModel:
    """ONNX Runtime backend -- the intended production path on CPU.

    Takes an ONNX graph exported and INT8-quantised offline, which cannot be
    written until a model is chosen (see MODEL_CANDIDATES). Note that the study
    laptop (Whiskey Lake) has no VNNI, so expect roughly 1.5-2.5x from
    quantisation rather than the 3-4x seen on newer Intel parts. Measure before
    relying on it.
    """

    def __init__(self, onnx_path: str, vocab: dict[str, int],
                 blank_id: int = 0, frame_stride_s: float = 0.02,
                 num_threads: int | None = None, model_id: str = "onnx"):
        import onnxruntime as ort

        options = ort.SessionOptions()
        if num_threads:
            options.intra_op_num_threads = num_threads
        self._session = ort.InferenceSession(
            onnx_path, sess_options=options, providers=["CPUExecutionProvider"],
        )
        self._input_name = self._session.get_inputs()[0].name
        self._model_id = model_id
        self._frame_stride_s = frame_stride_s
        self.phone_to_id, self.id_to_phone = _normalise_vocab(vocab)
        self.blank_id = blank_id
        self._n_labels = len(vocab)

    def describe(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._model_id, backend="onnx", device="cpu",
            n_labels=self._n_labels, inventory=tuple(sorted(self.phone_to_id)),
            frame_stride_s=self._frame_stride_s,
        )

    def warmup(self) -> None:
        self.emissions(np.zeros(8000, dtype=np.float32), 16_000)

    def emissions(self, waveform: np.ndarray, sample_rate: int) -> Emissions:
        started = time.perf_counter()
        x = waveform.astype(np.float32)
        # Zero-mean unit-variance normalisation, as wav2vec2 feature extractors
        # apply. Kept explicit here because the ONNX graph has no processor.
        x = (x - x.mean()) / (x.std() + 1e-7)
        logits = self._session.run(None, {self._input_name: x[None, :]})[0][0]
        shifted = logits - logits.max(axis=-1, keepdims=True)
        log_probs = shifted - np.log(np.exp(shifted).sum(axis=-1, keepdims=True))
        return Emissions(
            log_probs=log_probs.astype(np.float64),
            phone_to_id=self.phone_to_id, id_to_phone=self.id_to_phone,
            blank_id=self.blank_id, frame_stride_s=self._frame_stride_s,
            inference_ms=(time.perf_counter() - started) * 1000.0,
        )


class StubAcousticModel:
    """Deterministic fake emissions synthesised from a phone script.

    Exists so the whole scoring path -- alignment, GOP, classification,
    feedback -- can be tested without a 400 MB download, and so tests can
    construct exact error cases ("the learner said T where TH was expected,
    confidently") that are hard to elicit from real audio on demand.

    Emissions are deliberately **peaky**, like a real trained CTC model: one
    confident frame per phone with blank dominating everything around it. An
    earlier version spread confidence evenly across every frame with no blank
    at all, and because of that it could not reproduce the failure mode that
    took two rounds of debugging on real audio -- flat averaging over
    blank-dominated frames burying the signal. A stub that cannot express the
    bug cannot guard against it.
    """

    def __init__(self, produced: Sequence[str] = (), frames_per_phone: int = 5,
                 confidence: float = 0.9, frame_stride_s: float = 0.02):
        self.produced = [p.upper() for p in produced]
        self.frames_per_phone = frames_per_phone
        self.confidence = confidence
        self._frame_stride_s = frame_stride_s
        self.blank_id = 0
        # id 0 is the blank; phones occupy 1..N
        self.phone_to_id = {p: i + 1 for i, p in enumerate(ARPABET_PHONES)}
        self.id_to_phone = {i: p for p, i in self.phone_to_id.items()}

    def describe(self) -> ModelInfo:
        return ModelInfo(
            model_id="stub", backend="stub", device="cpu",
            n_labels=max(self.phone_to_id.values(), default=self.blank_id) + 1,
            inventory=tuple(sorted(self.phone_to_id)),
            frame_stride_s=self._frame_stride_s,
        )

    def warmup(self) -> None:  # nothing to warm
        return None

    def emissions(self, waveform: np.ndarray, sample_rate: int) -> Emissions:
        # Size from the highest id, not the label count: a test that removes a
        # phone from the inventory leaves the remaining ids sparse, and sizing
        # by count would then index past the end of the matrix.
        n_labels = max(self.phone_to_id.values(), default=self.blank_id) + 1
        n_frames = max(len(self.produced) * self.frames_per_phone, 1)

        residual = (1.0 - self.confidence) / max(n_labels - 1, 1)
        probs = np.full((n_frames, n_labels), residual)
        # Blank owns every frame except the per-phone peaks.
        probs[:, self.blank_id] = self.confidence

        for i, phone in enumerate(self.produced):
            pid = self.phone_to_id.get(phone)
            if pid is None:
                continue
            peak = i * self.frames_per_phone + self.frames_per_phone // 2
            if peak >= n_frames:
                continue
            probs[peak, :] = residual
            probs[peak, pid] = self.confidence

        probs /= probs.sum(axis=1, keepdims=True)
        return Emissions(
            log_probs=np.log(probs),
            phone_to_id=self.phone_to_id, id_to_phone=self.id_to_phone,
            blank_id=self.blank_id, frame_stride_s=self._frame_stride_s,
        )


_CACHE: dict[str, AcousticModel] = {}


def load_acoustic_model(config: PipelineConfig, num_threads: int | None = None
                        ) -> AcousticModel:
    """Load (and cache) the backend named by ``config``.

    Cached by config hash because model construction costs seconds and must
    happen once per process, at start-up, not per request.
    """
    key = config.config_hash()
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    if config.backend == "stub":
        model: AcousticModel = StubAcousticModel(frame_stride_s=config.frame_stride_s)
    elif config.backend == "torch":
        if not config.model_id:
            raise ValueError("config.model_id must be set for the torch backend")
        model = HFCTCAcousticModel(
            config.model_id, device=config.device,
            frame_stride_s=config.frame_stride_s, num_threads=num_threads,
        )
    elif config.backend == "onnx":
        raise ValueError(
            "the ONNX backend takes an exported graph and vocab; construct "
            "OnnxCTCAcousticModel directly from scripts/export_onnx.py output"
        )
    else:
        raise ValueError(f"unknown backend {config.backend!r}")

    _CACHE[key] = model
    return model
