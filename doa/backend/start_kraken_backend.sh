#! /bin/bash
eval "$(conda shell.bash hook)"
conda activate kraken
/home/admin/miniforge3/envs/kraken/bin/python3 kraken_main.py
