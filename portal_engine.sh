#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
#   MikroTik Captive Portal Engine — Automatic Hotspot & Redirect Controller
#   (Requires Root / tsu in Termux)
# =============================================================================

set -e

# ── Color codes ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║    MikroTik Captive Portal — Hotspot Engine (Root)   ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${YELLOW}[*] রুট এক্সেস প্রয়োজন। 'tsu' এর মাধ্যমে রুট নেওয়া হচ্ছে...${NC}"
    exec tsu -c "$0" "$@"
    exit $?
fi

# Detect hotspot interface and IP automatically
echo -e "${YELLOW}[1/4] হটস্পট ইন্টারফেস ও আইপি শনাক্ত করা হচ্ছে...${NC}"

HOTSPOT_IFACE=""
HOTSPOT_IP=""

# Try finding interface with private IP (192.168.x.x, 172.x.x.x, 10.x.x.x)
for iface in wlan0 ap0 wlan1 wlan2 swlan0 rndis0 tether; do
    IP=$(ip -4 addr show "$iface" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n 1 || true)
    if [ -n "$IP" ]; then
        HOTSPOT_IFACE="$iface"
        HOTSPOT_IP="$IP"
        break
    fi
done

if [ -z "$HOTSPOT_IP" ]; then
    # Fallback search any non-lo interface
    HOTSPOT_IFACE=$(ip -4 route show | grep -v 'default' | awk '{print $3}' | head -n 1 || echo "wlan0")
    HOTSPOT_IP=$(ip -4 addr show "$HOTSPOT_IFACE" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n 1 || echo "192.168.43.1")
fi

echo -e "${GREEN}[✓] ইন্টারফেস: ${BOLD}$HOTSPOT_IFACE${NC}${GREEN} | আইপি: ${BOLD}$HOTSPOT_IP${NC}"

# 1. Enable Kernel IP Forwarding
echo -e "${YELLOW}[2/4] কার্নেল আইপি ফরওয়ার্ডিং চালু করা হচ্ছে...${NC}"
echo 1 > /proc/sys/net/ipv4/ip_forward

# 2. Configure iptables for Captive Portal
echo -e "${YELLOW}[3/4] iptables ক্যাপটিভ পোর্টাল রুলস প্রয়োগ করা হচ্ছে...${NC}"

# Clean existing rules
iptables -t nat -F PREROUTING 2>/dev/null || true
# Redirect Port 80 & 443 HTTP/HTTPS to Flask 8080
iptables -t nat -I PREROUTING 1 -p tcp --dport 80 -j REDIRECT --to-port 8080
iptables -t nat -I PREROUTING 1 -p tcp --dport 443 -j REDIRECT --to-port 8080

# Redirect DNS Port 53 UDP/TCP to Port 5353 (dnsmasq)
iptables -t nat -I PREROUTING 1 -p udp --dport 53 -j REDIRECT --to-port 5353
iptables -t nat -I PREROUTING 1 -p tcp --dport 53 -j REDIRECT --to-port 5353

# Allow established connections & DNS locally
iptables -I FORWARD 1 -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true

# STRICT BLOCK: Force captive portal sign-in by dropping unauthenticated forward traffic
iptables -I FORWARD 2 -j DROP

echo -e "${GREEN}[✓] iptables কনফিগারেশন সম্পন্ন!${NC}"

# 3. Start dnsmasq DNS Spoofing in background
echo -e "${YELLOW}[4/4] DNS Spoofing (dnsmasq) শুরু করা হচ্ছে...${NC}"
killall dnsmasq 2>/dev/null || true
sleep 1

dnsmasq -k \
    -a "$HOTSPOT_IP" \
    --address="/#/$HOTSPOT_IP" \
    -p 5353 \
    --no-resolv \
    --no-poll \
    --log-facility=- > /dev/null 2>&1 &

DNSMASQ_PID=$!
echo -e "${GREEN}[✓] DNS সার্ভার চালু হয়েছে (PID: $DNSMASQ_PID)${NC}"

echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}   ক্যাপটিভ পোর্টাল ইঞ্জিন সম্পূর্ণ সক্রিয়!${NC}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════${NC}"
echo -e "  🌐 পোর্টাল URL : ${CYAN}http://$HOTSPOT_IP:8080/${NC}"
echo -e "  🔐 অ্যাডমিন    : ${CYAN}http://$HOTSPOT_IP:8080/admin${NC}"
echo -e "  📱 যে কোনো মোবাইল হটস্পটে যুক্ত হলেই 'Sign in to network' পপআপ আসবে।"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════════════════${NC}"
echo ""

# Start Flask App
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python &>/dev/null; then
    exec python app.py
else
    exec python3 app.py
fi
