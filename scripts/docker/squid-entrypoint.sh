#!/bin/sh
set -eu

llm_enabled="${AI_LLM_ENABLED:-false}"
llm_host="${AI_LLM_EGRESS_HOST:-}"

case "$llm_enabled" in
    true|True|TRUE|1)
        case "$llm_host" in
            ""|*[!A-Za-z0-9.-]*|.*|*..*|*.)
                echo "AI LLM egress host is missing or invalid." >&2
                exit 1
                ;;
        esac
        ;;
    *)
        llm_host=""
        ;;
esac

config_file="/tmp/identitytwin-squid.conf"
cat > "$config_file" <<'EOF'
http_port 3128

acl CONNECT method CONNECT
acl SSL_ports port 443
acl paypal_sandbox dstdomain api-m.sandbox.paypal.com
acl forbidden_destination dst 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.0.0.0/24 192.168.0.0/16 198.18.0.0/15 224.0.0.0/4 240.0.0.0/4 ::/128 ::1/128 fc00::/7 fe80::/10

http_access deny !SSL_ports
http_access deny CONNECT !SSL_ports
http_access deny forbidden_destination
http_access allow CONNECT paypal_sandbox
EOF

if [ -n "$llm_host" ]; then
    printf 'acl llm_provider dstdomain %s\nhttp_access allow CONNECT llm_provider\n' "$llm_host" >> "$config_file"
fi

printf 'http_access deny all\n' >> "$config_file"
exec /usr/sbin/squid -N -f "$config_file"
