# RecoverX — ابدأ من هنا (Ubuntu أو WSL2)

ده إصدار مُحسّن من المشروع مع إصلاحات سلامة الأدلة، تثبيت نموذج CART الموجود في المشروع، تجربة FAT16 آمنة وتصدير تقرير PDF. **استخدم فقط Disk Images أنت مصرح لك بفحصها.**

## 1) التثبيت (Ubuntu)

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip unzip sleuthkit testdisk dosfstools e2fsprogs mtools
cd RecoverX-main
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/install_bundled_model.py
python scripts/check_environment.py
python -m pytest -q
```

- في **Windows** الأفضل Ubuntu على **WSL2**. نفذ الأوامر داخله.
- لو عندك البرنامج بالفعل، احذف الـ virtualenv القديم فقط عند الحاجة وأعد إنشاؤه؛ متحذفش مجلد `workspace/` الخاص بنتائجك.
- `check_environment.py` محتاج يلاقي TSK وPhotoRec. لو مش موجودين هيوضح الناقص.
- النموذج المرفق تم تدريبه بإصدار scikit-learn 1.9.1. استخدم بيئة بنفس الإصدار قدر الإمكان؛ تحميل `joblib` بين إصدارات مختلفة قد يسبب تحذيرًا أو اختلافًا، ولا تفتح نماذج من مصادر غير موثوقة.

## 2) تشغيل الواجهة

```bash
streamlit run app.py
```

افتح `http://localhost:8501`، ثم:

1. **Case Management → Safe demo → Generate demo image and create case**. ده بيعمل صورة FAT16 وهمية 48 MiB فيها ملفات محذوفة، وليس جهازك الحقيقي.
2. **Forensic Analysis → Run pre-recovery analysis**: يعرض معلومات الملفات المحذوفة.
3. **Intelligent Recovery**: اختار **Fixed strategy** ثم **combined**، وسيُحدّد Ground Truth الخاص بالـ Demo تلقائيًا. سيظهر تقدم المراحل.
4. **Recovered Files**: شوف الملفات الموجودة والـ SHA-256. كلمة `verified_exact_match` لها معنى في الـ Demo فقط لأن عندنا Ground Truth.
5. **Evidence & Audit → Export forensic case report (PDF)**: نزّل ملخصًا من بيانات العملية.
6. جرّب تاني باستراتيجية **CART** وشوف الاستراتيجية المختارة، وقد يظهر اختيار Rule-v1 لو النموذج غير متاح.

## 3) نموذج CART المحفوظ

```bash
python scripts/install_bundled_model.py
```

يمكن تثبيته أيضًا من **Overview**. بيانات البحث القديمة موجودة في `research/results/exp1/` وتظهر في **Show advanced research pages** كـ **historical read-only results**. لا تمثل نتائج جهازك الحالي.

## 4) حاجات لازم تعرفها

- لو ملفات الـ Evidence اتغيرت بعد إنشاء الـ Case، البرنامج **هيوقف الفحص/الاسترجاع**؛ لا تحاول تجاوز ذلك، أنشئ Case جديدة للصورة المعدلة.
- PDF هو ملخص مراجعة، **مش إثبات قانوني لسلسلة حيازة الدليل**.
- الاسترجاع مش مضمون، خصوصًا لو البيانات اتكتبت فوقها. PhotoRec ممكن يرجع ملف من غير الاسم الأصلي.
- دعم TSK للـ partition offsets أحسن لما يكون اختيار **Inspect filesystem and partition offset** مفعّل. PhotoRec يستخدم اكتشافه الخاص والـ partitioned images محتاجة اختبار مستقل.
- لو بعض اختبارات pytest اتعملت `SKIPPED`، معناها الأدوات المطلوبة مش مثبتة، مش نجاح ضمني.
