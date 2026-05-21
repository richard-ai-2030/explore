#!/usr/bin/env bash
set -euo pipefail

API="${API:-http://127.0.0.1:8888/api}"
TS=$(date +%Y%m%d%H%M%S); 

register=$(curl -s -X POST "$API/auth/register" -H "Content-Type: application/json" -d "{\"name\":\"Smoke_User_${TS}\",\"email\":\"smoke_user_${TS}@example.com\",\"password\":\"Password123!\",\"roles\":[\"marketing\"]}")
echo $register

token=$(printf '%s' "$register" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')

[ -n "$token" ]
curl -s -f -X POST "$API/marketing/workflow/lead-to-order" -H "Authorization: Bearer $token" -H 'Content-Type: application/json' -d '{"lead":{"company":"Exploring Corp","fit":88,"intent":79,"urgency":72},"quotation":{"items":[{"qty":2,"price":5000}]},"order":{"quantity":2,"unitPrice":5000}}'

curl -s -f -X GET "$API/marketing/dashboard" -H "Authorization: Bearer $token"

echo "Staging smoke test - Marketing PASSED"