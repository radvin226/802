# بات علوم ۸۰۲ سید رضی — Bale API

این نسخه برای API بله ساخته شده و فیلتر چندزبانه‌ی profanity را از `safetext` استفاده می‌کند.

## نصب

```bash
pip install -r requirements.txt
```

توکن را در متغیر محیطی `BALE_TOKEN` بگذار:

```bash
BALE_TOKEN="توکن_بله" python main.py
```

یا مقدار پیش‌فرض داخل `main.py` را تغییر بده.

## فیلتر فحش

`moderation.py` از فهرست‌های داخلی SafeText استفاده می‌کند. این روش بهتر از چسباندن هزاران واژه‌ی صریح داخل `main.py` است و نسخه‌ی فعلی SafeText برای ۱۳ زبان از جمله فارسی، انگلیسی، عربی، آذری، روسی و ترکی فهرست داخلی دارد.

هیچ فهرست «تمام فحش‌های جهان» واقعاً کامل نیست؛ زبان و slang دائماً تغییر می‌کند و فهرست‌های واژه‌ای هم false positive دارند.

## PDF

فایل‌های PDF را در این مسیرها قرار بده:

- `pdfs/text/01.pdf` تا `15.pdf`
- `pdfs/samples/first_term.pdf`
- `pdfs/samples/second_term.pdf`
- `pdfs/samples/comprehensive.pdf`
