# 📡 MikroTik-Style Captive Portal & WiFi Hotspot Management System

**Platform:** Termux (Android) · **Framework:** Flask · **Database:** SQLite3 · **Single File:** `app.py`

---

## ✨ সিস্টেম ফিচার ও ফাংশন

- 🔐 **ক্যাপটিভ পোর্টাল লগইন** — হটস্পটে কানেক্ট হওয়া মাত্র ৪-ডিজিট ভাউচার পিন পেজ পপআপ হয়
- 🎟️ **ভাউচার পিন সিস্টেম** — র‍্যান্ডম বা কাস্টম ৪-ডিজিট পিন জেনারেট করুন; Active/Used স্ট্যাটাস ট্র্যাক হয়
- 📊 **অ্যাডমিন ড্যাশবোর্ড** — মোট পিন, অ্যাক্টিভ পিন, ব্যবহৃত পিন ও অনলাইন ইউজার সংখ্যার লাইভ স্ট্যাট
- 🟢 **লাইভ সেশন মনিটর** — কোন IP কোন পিন দিয়ে কখন কানেক্ট হয়েছে তা দেখুন
- 🚫 **User Kick** — যেকোনো কানেক্টেড ডিভাইসকে এক ক্লিকে নেটওয়ার্ক থেকে বিচ্ছিন্ন করুন
- 🗑️ **পিন ম্যানেজমেন্ট** — পিন ডিলিট করুন; সব ব্যবহৃত পিন এক ক্লিকে পরিষ্কার করুন
- 🖨️ **প্রিন্টযোগ্য ভাউচার কার্ড** — অ্যাক্টিভ পিনগুলো কাস্টমারদের দেওয়ার জন্য প্রিন্ট-রেডি কার্ড ভিউ
- ⚙️ **অ্যাডমিন সেটিংস** — ইউজারনেম ও পাসওয়ার্ড যেকোনো সময় পরিবর্তন করুন
- 🤖 **OS Auto-Detect** — Android, Apple iOS, Windows, Chrome — সব ডিভাইসের captive portal চেক ধরা পড়ে
- 🛡️ **iptables Integration** — অথেনটিকেটেড IP স্বয়ংক্রিয়ভাবে ইন্টারনেট পায়; লগআউটে রুল মুছে যায়
- 🗄️ **SQLite3 Database** — কোনো আলাদা ডাটাবেস সার্ভার ছাড়াই সব ডেটা `hotspot.db`-এ সেভ থাকে

---

## 📁 প্রজেক্ট স্ট্রাকচার

```
MikroTik-Style-Captive-Portal/
├── app.py            ← সম্পূর্ণ সিস্টেম (Flask + UI + DB + iptables Logic)
├── requirements.txt  ← Python ডিপেন্ডেন্সি
├── hotspot.db        ← SQLite ডাটাবেস (প্রথম রানেই অটো-তৈরি হয়)
└── README.md         ← এই গাইড
```

---

## 🚀 Termux-এ প্রথমবার সম্পূর্ণ সেটআপ

নতুন ফোনে Termux ইনস্টল করার পর নিচের কমান্ডগুলো **একটি একটি করে** রান করুন:

### ধাপ ১ — Termux বেসিক আপডেট ও আপগ্রেড

```bash
pkg update -y && pkg upgrade -y
```

> ⏳ এটি কিছুটা সময় নেবে। মাঝে মাঝে `[Y/n]` জিজ্ঞেস করলে `Y` লিখে Enter চাপুন।

---

### ধাপ ২ — Python ইনস্টল করুন

```bash
pkg install -y python
```

Python ঠিকমতো ইনস্টল হয়েছে কিনা যাচাই করুন:

```bash
python --version
```

আউটপুট দেখাবে: `Python 3.x.x`

---

### ধাপ ৩ — pip আপগ্রেড করুন

```bash
pip install --upgrade pip
```

---

### ধাপ ৪ — Git ইনস্টল করুন

```bash
pkg install -y git
```

যাচাই করুন:

```bash
git --version
```

---

### ধাপ ৫ — রিপোজিটরি ক্লোন করুন

```bash
git clone https://github.com/busnesssubscribe10-afk/MikroTik-Style-Captive-Portal-WiFi-Hotspot-Management-System.git
```

---

### ধাপ ৬ — প্রজেক্ট ফোল্ডারে প্রবেশ করুন

```bash
cd MikroTik-Style-Captive-Portal-WiFi-Hotspot-Management-System
```

---

### ধাপ ৭ — Flask ও Werkzeug ইনস্টল করুন

```bash
pip install -r requirements.txt
```

---

### ধাপ ৮ — সার্ভার চালু করুন ✅

```bash
python app.py
```

সফলভাবে চালু হলে আউটপুট দেখাবে:
```
[+] Server running at: http://0.0.0.0:8080
[+] Admin Dashboard:  http://0.0.0.0:8080/admin
[+] Default Admin:    Username: admin | Password: admin
```

---

## 🔄 পরেরবার সার্ভার চালু করতে

```bash
cd MikroTik-Style-Captive-Portal-WiFi-Hotspot-Management-System && python app.py
```

---

## 🔃 সর্বশেষ আপডেট নামাতে (git pull)

```bash
cd MikroTik-Style-Captive-Portal-WiFi-Hotspot-Management-System
git pull origin main
python app.py
```

---

## 🌐 অ্যাক্সেস URL সমূহ

হটস্পট গেটওয়ে IP বের করুন:

```bash
ip addr show wlan0 | grep "inet "
```

তারপর:

| পেজ | URL |
|---|---|
| 👤 ইউজার পোর্টাল | `http://192.168.43.1:8080/` |
| 🔐 অ্যাডমিন প্যানেল | `http://192.168.43.1:8080/admin` |
| ⚙️ সেটিংস | `http://192.168.43.1:8080/admin/settings` |
| 🎟️ ভাউচার ম্যানেজমেন্ট | `http://192.168.43.1:8080/admin/vouchers` |

---

## 🔐 ডিফল্ট অ্যাডমিন ক্রেডেনশিয়াল

```
Username : admin
Password : admin
```

> ⚠️ প্রথম লগইনের পরেই **Settings** থেকে পাসওয়ার্ড পরিবর্তন করুন!

---

## 📡 ক্যাপটিভ পোর্টাল ট্রিগার সেটআপ (Rooted Android)

> iptables ছাড়া ইউজার লগইন পেজে **স্বয়ংক্রিয়ভাবে** যাবে না।  
> এই ধাপগুলো শুধু **Rooted Android** ডিভাইসে কাজ করবে।

### iptables ও dnsmasq ইনস্টল (একবারই করতে হবে)

```bash
pkg install -y root-repo
pkg install -y iptables dnsmasq tsu
```

### রুট শেল নিন

```bash
tsu
```

### IP Forwarding চালু করুন

```bash
echo 1 > /proc/sys/net/ipv4/ip_forward
```

### সব HTTP/DNS ট্রাফিক Flask-এ পাঠান

```bash
iptables -t nat -F
iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80 -j REDIRECT --to-port 8080
iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 443 -j REDIRECT --to-port 8080
iptables -t nat -A PREROUTING -i wlan0 -p udp --dport 53 -j REDIRECT --to-port 5353
```

### DNS Spoofing চালু করুন (নতুন সেশনে)

```bash
dnsmasq -k -a 192.168.43.1 --address=/#/192.168.43.1 -p 5353 --no-resolv --no-poll &
```

### Flask সার্ভার চালু করুন (নতুন সেশনে)

```bash
python app.py
```

> 💡 **টিপস:** Termux-এ একাধিক সেশন খুলতে স্ক্রিনের বাম থেকে সোয়াইপ করুন → New Session।

---

## 🔁 সিস্টেম ওয়ার্কফ্লো

```
ইউজার WiFi হটস্পটে কানেক্ট করে
           ↓
Android/iOS/Windows OS → Captive Portal চেক (generate_204, hotspot-detect.html ইত্যাদি)
           ↓
Flask → Redirect → ভাউচার লগইন পেজ দেখায়
           ↓
ইউজার ৪-ডিজিট পিন দেয়
           ↓
SQLite চেক → পিন Active? → পিন "used" মার্ক হয়, Session তৈরি হয়
           ↓
iptables → ওই IP-এর জন্য ACCEPT রুল যোগ হয়
           ↓
ইউজার সম্পূর্ণ ইন্টারনেট এক্সেস পায় ✅
```

---

## 🛠️ সমস্যা সমাধান

| সমস্যা | সমাধান |
|---|---|
| `ModuleNotFoundError: flask` | `pip install flask werkzeug` চালান |
| `command not found: python` | `pkg install python` চালান |
| ক্যাপটিভ পোর্টাল পপআপ হচ্ছে না | iptables রিডাইরেক্ট সেটআপ করুন (উপরে দেখুন) |
| iptables কাজ করছে না | রুটেড ডিভাইস ও `tsu` দরকার |
| IP ভিন্ন | `ip addr show wlan0` দিয়ে সঠিক IP বের করুন |
| পোর্ট ৮০৮০ বিজি | `pkill -f app.py` চালিয়ে আবার শুরু করুন |

---

## 🪪 লাইসেন্স

শুধুমাত্র শিক্ষামূলক ও ব্যক্তিগত ব্যবহারের জন্য।
