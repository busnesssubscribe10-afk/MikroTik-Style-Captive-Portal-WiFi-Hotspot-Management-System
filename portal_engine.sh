#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
#   MikroTik Captive Portal Engine — Smart Controller (Root & Non-Root)
# =============================================================================

# ── Color codes ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║    MikroTik Captive Portal — Smart Engine Controller     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Detect Hotspot IP & Interface automatically
HOTSPOT_IFACE=""
HOTSPOT_IP=""

for iface in wlan0 ap0 wlan1 wlan2 swlan0 rndis0 tether; do
    IP=$(ip -4 addr show "$iface" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n 1 || true)
    if [ -n "$IP" ]; then
        HOTSPOT_IFACE="$iface"
        HOTSPOT_IP="$IP"
        break
    fi
done

if [ -z "$HOTSPOT_IP" ]; then
    HOTSPOT_IP=$(ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\s)192\.168\.\d+\.\d+' | head -n 1 || true)
fi

if [ -z "$HOTSPOT_IP" ]; then
    HOTSPOT_IP="192.168.43.1"
    HOTSPOT_IFACE="wlan0"
fi

echo -e "${GREEN}[1/3] হটস্পট আইপি শনাক্ত হয়েছে: ${BOLD}$HOTSPOT_IP${NC} (ইন্টারফেস: ${HOTSPOT_IFACE:-auto})"

# Check Root Access
echo -e "${YELLOW}[2/3] রুট (Superuser) পরিবেশ চেক করা হচ্ছে...${NC}"

IS_ROOT=false
if [ "$(id -u)" -eq 0 ]; then
    IS_ROOT=true
elif command -v su &>/dev/null && su -c "id" 2>/dev/null | grep -q "uid=0"; then
    IS_ROOT=true
fi

if [ "$IS_ROOT" = true ]; then
    echo -e "${GREEN}[✓] রুট মোড সক্রিয়! পূর্ণাঙ্গ iptables ও স্বয়ংক্রিয় পপআপ কনফিগার করা হচ্ছে...${NC}"

    # 1. Enable Kernel IP Forwarding
    echo 1 > /proc/sys/net/ipv4/ip_forward 2>/dev/null || true

    # 2. Configure iptables for strict captive portal
    iptables -t nat -F PREROUTING 2>/dev/null || true
    iptables -t nat -I PREROUTING 1 -p tcp --dport 80 -j REDIRECT --to-port 8080 2>/dev/null || true
    iptables -t nat -I PREROUTING 1 -p tcp --dport 443 -j REDIRECT --to-port 8080 2>/dev/null || true
    iptables -t nat -I PREROUTING 1 -p udp --dport 53 -j REDIRECT --to-port 5353 2>/dev/null || true
    iptables -t nat -I PREROUTING 1 -p tcp --dport 53 -j REDIRECT --to-port 5353 2>/dev/null || true

    iptables -I FORWARD 1 -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true
    iptables -I FORWARD 2 -j DROP 2>/dev/null || true

    # 3. Start dnsmasq
    killall dnsmasq 2>/dev/null || true
    dnsmasq -k -a "$HOTSPOT_IP" --address="/#/$HOTSPOT_IP" -p 5353 --no-resolv --no-poll >/dev/null 2>&1 &
else
    echo -e "${YELLOW}[!] আপনার ফোনটি আনরুটেড (Non-Rooted)।${NC}"
    echo -e "${GREEN}[✓] নন-রুট স্মার্ট গেটওয়ে মোডে পোর্টাল চালু হচ্ছে...${NC}"
fi

echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}   ক্যাপটিভ পোর্টাল সার্ভার সক্রিয় হয়েছে!               ${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════${NC}"
echo -e "  🌐 ইউজার পোর্টাল URL : ${CYAN}${BOLD}http://$HOTSPOT_IP:8080/${NC}"
echo -e "  🔐 অ্যাডমিন প্যানেল  : ${CYAN}${BOLD}http://$HOTSPOT_IP:8080/admin${NC}"
echo -e "  👤 ডিফল্ট লগইন       : ${BOLD}admin / admin${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "💡 ${YELLOW}টিপস:${NC} যে কোনো মোবাইল থেকে আপনার হটস্পটে যুক্ত হয়ে ব্রাউজারে"
echo -e "       ${CYAN}http://$HOTSPOT_IP:8080/${NC} ওপেন করলেই ৪-ডিজিট পিন ও প্যাকেজ পেজ চলে আসবে।"
echo ""

# Start Flask App
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python &>/dev/null; then
    exec python app.py
else
    exec python3 app.py
fi
