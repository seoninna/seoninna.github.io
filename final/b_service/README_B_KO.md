# APPROVED_EXTERNAL_B 비교 서비스 (선택, 기본 OFF)

**외부 처리 허가를 받은 자료 또는 비기밀 재제작 자료만** 처리합니다. 회사 원화를 이 경로로 보내지 마세요.

| 항목 | 내용 |
|---|---|
| 입력 | n8n B안이 보낸 before/after PDF 2개 (multipart), category_code, artwork_id, 선택: requests_json, page_map_json |
| 처리 | `final_check` 엔진으로 텍스트·시각 비교. 임시 폴더에서 처리 후 삭제 |
| 출력 | 안전 요약 JSON + 이미지 포함 HTML 보고서(base64) |
| 외부 AI | 호출하지 않음 (`cloud_llm_enabled=true`면 시작 거부) |
| 거부 조건 | privacy_mode ≠ APPROVED_EXTERNAL_B, root_dir/output_dir 존재, 승인 기록 미기재, 토큰 24자 미만, 업로드 한도 초과(잘라내지 않음) |

## 로컬에서 먼저 시험 (비기밀 합성 자료)
```bash
cp config.b.example.json config.b.json
```
`config.b.json`에서 `approval`(승인자·일자·범위)과 `service.token`(24자 이상 임의 문자열)을 채운 뒤:
```bash
python b_service/b_service.py --config config.b.json
```

## Railway 등 클라우드 배포 (사용자가 직접 결정)
- 이 저장소는 **자동 배포·자동 업로드를 하지 않습니다.** 배포는 승인 범위를 확인한 뒤 본인이 직접 합니다.
- `b_service/Dockerfile` 사용. 컨테이너 안에서는 `service.host`를 `0.0.0.0`으로 두어야 외부 포트가 연결됩니다. 포트는 `PORT` 환경변수를 따릅니다.
- `config.b.json`은 이미지에 넣지 말고 비밀 파일/볼륨으로 제공하세요. 토큰은 `FINAL_B_TOKEN` 환경변수로도 줄 수 있습니다.
- 업로드 한도는 `max_upload_mb`. Gmail 첨부 한도(일반적으로 25MB, 현재 정책은 Google 공식 문서에서 재확인), n8n의 바이너리 메모리 설정(`N8N_DEFAULT_BINARY_DATA_MODE=filesystem` 권장), 서버 메모리를 함께 확인하세요. **한도를 넘는 파일은 잘라서 비교하지 않고 거부합니다.**
- 미검증: 실제 Railway 배포, 실제 Gmail/Drive 연동, 메모리 사용량.
