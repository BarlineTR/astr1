#!/usr/bin/env python3
"""ASTRO V1 — Heterogeneous Inference Abstraction Layer & Circuit Breaker.

Provides a unified interface across:
  - TensorRT / CUDA Local GPU Inference (Jetson Ampere)
  - ONNX Runtime (CPU / CUDA Execution Providers)
  - Cloud APIs (Groq / OpenAI) with Circuit Breaker pattern
"""

import enum
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("astro_inference")


class CircuitState(enum.Enum):
    CLOSED = "CLOSED"      # Normal operation: Cloud primary is healthy
    OPEN = "OPEN"          # Cloud failed: Routing requests to Local Fallback
    HALF_OPEN = "HALF_OPEN"# Testing cloud recovery with probe requests


class CircuitBreaker:
    """Manages automatic fallback between cloud and local inference engines.
    
    Rules:
      - 3 consecutive failures -> OPEN circuit (switch to local)
      - After cooldown (default 30s) -> HALF_OPEN (test next request on cloud)
      - 1 successful probe in HALF_OPEN -> CLOSED (restore cloud)
      - Failure in HALF_OPEN -> return to OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_s: float = 30.0,
        name: str = "CloudCircuit"
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.name = name
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_state_change = time.monotonic()
        self.last_failure_time = 0.0

    def record_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.last_state_change = time.monotonic()
            logger.info(f"🟢 [{self.name}] Cloud bağlantısı kurtarıldı! Durum: CLOSED (Cloud Aktif)")
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    def record_failure(self, error_msg: str = ""):
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.last_state_change = time.monotonic()
            logger.warning(f"🔴 [{self.name}] Cloud ardışık {self.failure_count} kez başarısız ({error_msg}). Durum: OPEN (Yerel Mod Aktif)")
        elif self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.last_state_change = time.monotonic()
            logger.warning(f"⚠️ [{self.name}] Cloud deneme isteği başarısız oldu. Durum: OPEN (Yerel Mod Devam)")

    def should_use_cloud(self) -> bool:
        now = time.monotonic()
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            if (now - self.last_state_change) > self.recovery_timeout_s:
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = now
                logger.info(f"🟡 [{self.name}] Cloud iyileşme testi deneniyor... Durum: HALF_OPEN")
                return True
            return False
        elif self.state == CircuitState.HALF_OPEN:
            return True
        return False


class InferenceBackend(ABC):
    """Abstract base class for all inference execution providers."""

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the backend runtime and model weights are ready."""
        pass

    @abstractmethod
    def infer(self, input_data: Any) -> Any:
        """Runs synchronous or batch inference."""
        pass


class TensorRTBackend(InferenceBackend):
    """Jetson TensorRT GPU engine executor (FP16/INT8 accelerated)."""

    def __init__(self, engine_path: str):
        self.engine_path = engine_path
        self._engine = None
        self._context = None
        self._available = False
        self._init_engine()

    def _init_engine(self):
        if not os.path.exists(self.engine_path):
            return
        try:
            import tensorrt as trt
            TRT_LOGGER = trt.Logger(trt.Logger.WARNING)
            with open(self.engine_path, "rb") as f, trt.Runtime(TRT_LOGGER) as runtime:
                self._engine = runtime.deserialize_cuda_engine(f.read())
            if self._engine:
                self._context = self._engine.create_execution_context()
                self._available = True
        except Exception as e:
            logger.debug(f"TensorRT initialization notice for {self.engine_path}: {e}")
            self._available = False

    def is_available(self) -> bool:
        return self._available and self._context is not None

    def infer(self, input_data: Any) -> Any:
        if not self.is_available():
            raise RuntimeError(f"TensorRT engine not ready: {self.engine_path}")
        # Placeholder for buffer bindings & cuda memcpy
        return None


class ONNXBackend(InferenceBackend):
    """Lightweight ONNX Runtime backend with CPU / CUDA Execution Providers."""

    def __init__(self, model_path: str, prefer_cuda: bool = True):
        self.model_path = model_path
        self.prefer_cuda = prefer_cuda
        self._session = None
        self._available = False
        self._init_session()

    def _init_session(self):
        if not os.path.exists(self.model_path):
            return
        try:
            import onnxruntime as ort
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if self.prefer_cuda else ["CPUExecutionProvider"]
            self._session = ort.InferenceSession(self.model_path, providers=providers)
            self._available = True
        except Exception as e:
            logger.debug(f"ONNX session init notice for {self.model_path}: {e}")
            self._available = False

    def is_available(self) -> bool:
        return self._available and self._session is not None

    def infer(self, input_data: Any) -> Any:
        if not self.is_available():
            raise RuntimeError(f"ONNX model not ready: {self.model_path}")
        input_name = self._session.get_inputs()[0].name
        return self._session.run(None, {input_name: input_data})


class CloudBackend(InferenceBackend):
    """Cloud API backend wrapper with health checks."""

    def __init__(self, client: Any, model_name: str):
        self.client = client
        self.model_name = model_name

    def is_available(self) -> bool:
        return self.client is not None

    def infer(self, input_data: Any) -> Any:
        if not self.is_available():
            raise RuntimeError("Cloud client is not initialized or offline.")
        return None
