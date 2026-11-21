# تشغيل RecoverX v0.3.0 على Windows

1. ثبّت Python ‏64-bit بإصدار 3.11 أو 3.12 أو 3.13.
2. لتشغيل PhotoRec، ثبّت Ubuntu على WSL 2 واجعله التوزيعة الافتراضية. افتح Ubuntu بحساب عادي وشغّل `sudo apt update && sudo apt install testdisk`. يمكن استخدام TSK فقط بدون WSL.
3. شغّل `SETUP_WINDOWS.cmd` من مجلد قابل للكتابة، ثم شغّل `START_RECOVERX_WINDOWS.cmd`.
4. تفتح صفحة Quick Recovery أولًا. للوصول إلى التحليل والتقارير والصفحات المتقدمة، اختر **Show advanced pages** من القائمة الجانبية.

استخدم نسخة صورة قرص على قرص محلي يمكن لـ WSL الوصول إليه. لا يدعم التطبيق تصوير الأقراص المادية مباشرة على Windows. لا يحتاج التطبيق إلى تشغيله كمسؤول أو تغيير إعدادات UAC.
