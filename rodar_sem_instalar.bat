@echo off
chcp 65001 > nul
title Dashboard Inventario Rotativo
call venv\Scripts\activate
python app.py
pause
