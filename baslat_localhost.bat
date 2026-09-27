@echo off
chcp 65001 > nul
title ASTRO V1 — Localhost Baslatici

echo ========================================================
echo   🚀 ASTRO V1 Web Sitesi ve Robot Ag Gecidi Baslatiliyor
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/3] Ag Gecidi (Fastify Gateway :8420) baslatiliyor...
start "ASTRO Gateway (8420)" cmd /k "node --env-file=apps/site/.env.local apps/gateway/dist/index.js"

echo [2/3] Web Kontrol Paneli (Next.js :3000) baslatiliyor...
start "ASTRO Web Site (3000)" cmd /k "npm run dev:site"

echo [3/3] Jetson Baglanti Tuneli baslatiliyor...
start "ASTRO Jetson Bridge" cmd /k "python scripts\jetson_tunnel.py"

echo.
echo ========================================================
echo   ✅ Tum servisler baslatildi!
echo   Giris Bilgileri:
echo     Adres : http://localhost:3000/giris
echo     E-Posta: admin@astro.com
echo     Sifre : Password123!
echo ========================================================
echo.

timeout /t 3 > nul
start http://localhost:3000/giris
