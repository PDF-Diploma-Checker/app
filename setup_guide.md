# Setup

Requirements: Java 17+. For `cpu`/`gpu` you also need a C++ compiler and CMake. For `gpu` you also need the NVIDIA CUDA Toolkit (`nvcc`).

## Linux
For short analysis run:
```bash
./setup.sh
```
For short analysis + llm analysis on cpu run:
```bash
./setup.sh cpu
```
For short analysis + llm analysis on gpu run:
```bash
./setup.sh gpu
```
Then to run:
```bash
uv run src/app/main.py
```

## Windows (PowerShell)
For short analysis run:
```bash
.\setup.ps1 
```
For short analysis + llm analysis on cpu run:
```bash
.\setup.ps1 cpu
```
For short analysis + llm analysis on gpu run:
```bash
.\setup.ps1 gpu
```
Then to run:
```bash
uv run src/app/main.py
```

## Checking the GPU mode
Every time the app starts in the GPU variant, it checks in the background what the GPU mode needs and, if something is missing, shows a window with each missing piece and the next step:
- the AI libraries (`llama-cpp-python`) are not installed, or were built without CUDA: run `./setup.sh gpu` (Linux) or `.\setup.ps1 gpu` (Windows) again,
- no NVIDIA card was found, or the driver is too old (CUDA 12.0 or newer is needed): install or update the driver from nvidia.com/drivers,
- too little free video memory (the model fits whole from 8 GB): close other programs that use the card, or set fewer GPU layers in the AI setup,
- the AI models are not downloaded: open the AI setup and choose "Save and download the models" (about 14 GB), or put the files in the models folder shown in the window.

The window is shown again on every start while something is missing. Tick "Do not remind me about this again" to hide it for the current set of problems (it comes back if a new problem appears). Nothing is shown in the CPU variant, when the processor is chosen in the AI setup, or when everything is in place.
