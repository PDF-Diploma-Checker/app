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
or short analysis run:
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