URL="http://localhost"
TOTAL=1000
CONCURRENT=100

seq "$TOTAL" | xargs -P "$CONCURRENT" -I{} curl -s -o /dev/null "$URL"
