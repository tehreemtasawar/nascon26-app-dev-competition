#!/bin/sh
set -eu

BASE_URL="${BASE_URL:-http://localhost:8080}"

curl --fail --silent "$BASE_URL/health" | grep -q '"status":"ok"'
curl --fail --silent -X POST "$BASE_URL/audit/v1/reset" \
  -H 'Content-Type: application/json' -d '{}' | grep -q '"reset_complete"'
curl --fail --silent -X POST "$BASE_URL/audit/v1/fixtures" \
  -H 'Content-Type: application/json' \
  -d '{"format":"round_robin","teams":["t1","t2","t3"]}' | grep -q '"round_count":3'
curl --fail --silent -X POST "$BASE_URL/audit/v1/sports" \
  -H 'Content-Type: application/json' \
  -d '{"sport_id":"kabaddi","name":"Kabaddi","scoring_model":"event","periods":{"count":2,"duration_minutes":20},"scoring_events":{"raid_point":{"points":1}},"draw_allowed":false,"overtime":{"policy":"golden_score"},"roster":{"min_squad_size":7,"max_squad_size":12,"required_positions":{}}}' \
  | grep -q '"status":"created"'

echo "Backend smoke tests passed."
