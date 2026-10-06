@echo off
chcp 65001 > nul
title Turbo Scraper - Online Server

echo ========================================================
echo   🚀 تشغيل السيرفر وإنشاء رابط أونلاين عام مجاناً
echo ========================================================
echo.
echo [1/2] جاري تشغيل خادم الويب...
start "Turbo Scraper Backend" /min python app.py

timeout /t 3 /nobreak > nul

echo.
echo [2/2] جاري إنشاء وتوليد الرابط العام المشفر (HTTPS)...
echo.
echo ========================================================
echo   انسخ الرابط الذي سيظهر بالأسفل (.trycloudflare.com)
echo   وأرسله لأي شخص ليفتح الموقع ويستخدمه فوراً!
echo ========================================================
echo.

cloudflared.exe tunnel --url http://127.0.0.1:8000
