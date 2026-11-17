# The sherpa-onnx Python wheel used by the existing diagnostic includes its
# public C++ headers and shared libraries, so no second model runtime is needed.
SHERPA_ONNX_PREFIX ?= ../../reazonspeech/.venv/lib/python3.12/site-packages/sherpa_onnx
INCLUDE_DIR := $(SHERPA_ONNX_PREFIX)/include
LIB_DIR := $(SHERPA_ONNX_PREFIX)/lib
BUILD_DIR := ../build/native
TARGET := $(BUILD_DIR)/wakeword_kws

CXX ?= g++
CXXFLAGS ?= -O2 -std=c++17 -Wall -Wextra -Wpedantic

.PHONY: native-kws clean

native-kws: $(TARGET)

$(TARGET): wakeword_kws.cc tuner_pitch.h
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -I$(INCLUDE_DIR) $< -L$(LIB_DIR) -lsherpa-onnx-c-api -Wl,-rpath,$(abspath $(LIB_DIR)) -o $@

# Standalone Mirai experiment; header is obtained separately, runtime is loaded
# at execution time, keeping the existing sherpa-onnx build independent.
ONNXRUNTIME_INCLUDE ?= /tmp/foxbook-onnxruntime-include
.PHONY: mirai-kws
mirai-kws: $(BUILD_DIR)/mirai_kws

$(BUILD_DIR)/mirai_kws: mirai_kws.cc tuner_pitch.h
	mkdir -p $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) -I$(ONNXRUNTIME_INCLUDE) $< -ldl -o $@

clean:
	rm -rf $(BUILD_DIR)
