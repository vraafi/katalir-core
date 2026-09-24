# Railway Token Scope dan Sinkronisasi Environment

Terakhir diperbarui: 24 September 2026

Railway GraphQL endpoint: `https://backboard.railway.app/graphql/v2`. Gunakan header `Authorization: Bearer <RAILWAY_API_TOKEN>`. Scope `Account` adalah target untuk operasi tulis; jangan menyimpulkan hak tulis hanya dari format UUID. Verifikasi respons API dan scope di dashboard Railway.

## Target Katalir

Project `sunny-vibrancy` (`5c471234-02d3-4009-be71-9cd304e4d809`), service `web` (`996f34a1-da07-4ad0-adca-890b1b7f555b`), environment `production` (`b332795c-7882-490b-95fd-0f1079cd66b3`).

Backend membaca `SLACK_APP_ID`, `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_SIGNING_SECRET`, dan `SLACK_VERIFICATION_TOKEN`. Nilai secret dikirim langsung dari `.env` ke Railway API dan tidak boleh dicetak, di-commit, atau dimasukkan ke screenshot.

## Verifikasi

Setelah `variableUpsert` dan `serviceInstanceRedeploy`, cek `GET https://web-production-dc90b.up.railway.app/oauth/slack/status`. Target: `{"keys_present":5,"keys_total":5}`.

`variableUpsert=true` tetapi status `0/5` berarti sinkronisasi belum terbukti. Periksa deployment/service aktif dan log Railway; jangan mengklaim selesai hanya karena mutation mengembalikan 200.

## Troubleshooting

- `Not Authorized`: token tidak memiliki write scope atau target project/service salah.
- `variableUpsert=true`, status `0/5`: redeploy belum settling, domain production menunjuk deployment lain, atau variable tidak terpasang pada service target.
- Railway API 401: token kosong/kedaluwarsa atau belum di-load dengan `load_dotenv(override=True)`.
- Jangan retry mutation yang sudah mengembalikan 200 tanpa memeriksa respons.

Dokumentasi resmi: https://docs.railway.com/reference/public-api dan https://docs.railway.com/guides/variables
