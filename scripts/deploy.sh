#!/bin/bash
cd /home/gcorthey/congreso_nano
git fetch origin main
git reset --hard origin/main
sudo systemctl restart nano2026
