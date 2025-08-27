# GitHub Actions와 PowerAutomate 연동 설정 가이드

## 개요

이 가이드는 매일 아침 8시에 PowerAutomate에서 GitHub Actions를 트리거하여 뉴스 분석 및 이메일 전송을 자동화하는 방법을 설명합니다.

## 아키텍처

```
PowerAutomate (매일 8시) 
    ↓ TriggerGitHubAction
GitHub Actions (뉴스 수집 & 분석)
    ↓ HTTP Request
PowerAutomate (메일 전송)
```

## 설정 단계

### 1. GitHub 리포지토리 설정

#### 1.1 GitHub Secrets 설정
GitHub 리포지토리 → Settings → Secrets and variables → Actions에서 다음 secrets을 추가:

- `POWERAUTOMATE_WEBHOOK_URL`: PowerAutomate webhook URL
- `OPENAI_API_KEY`: OpenAI API 키 (필요한 경우)

#### 1.2 Repository Dispatch 설정
GitHub Actions workflow는 다음 방법으로 트리거될 수 있습니다:

1. **PowerAutomate에서 트리거**: `daily-news-trigger` 이벤트
2. **스케줄 실행**: 매일 23:00 UTC (한국시간 08:00)
3. **수동 실행**: GitHub Actions 탭에서 수동 실행

### 2. PowerAutomate 설정

#### 2.1 첫 번째 Flow: GitHub Actions 트리거

1. **트리거**: 되풀이 - 매일 오전 8:00
2. **액션**: HTTP 요청
   ```
   Method: POST
   URI: https://api.github.com/repos/{owner}/{repo}/dispatches
   Headers:
     - Authorization: Bearer {github_token}
     - Accept: application/vnd.github.v3+json
     - Content-Type: application/json
   Body:
   {
     "event_type": "daily-news-trigger",
     "client_payload": {
       "mode": "email",
       "timestamp": "@{utcNow()}"
     }
   }
   ```

#### 2.2 두 번째 Flow: 결과 수신 및 메일 전송

1. **트리거**: HTTP 요청이 수신된 경우
2. **액션**: 메일 전송
   - GitHub Actions에서 보낸 데이터를 기반으로 메일 생성

### 3. GitHub Actions Workflow 상세

#### 3.1 Workflow 파일: `.github/workflows/daily-news-mail.yml`

```yaml
name: Daily News Mail

on:
  repository_dispatch:
    types: [daily-news-trigger]
  schedule:
    - cron: '0 23 * * *'  # 매일 23:00 UTC (한국시간 08:00)
  workflow_dispatch:

jobs:
  send-daily-news:
    runs-on: ubuntu-latest
    
    steps:
    - name: Checkout repository
      uses: actions/checkout@v4
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r 250508/news_clipping/requirements.txt
    
    - name: Run news collection and email
      env:
        POWERAUTOMATE_WEBHOOK_URL: ${{ secrets.POWERAUTOMATE_WEBHOOK_URL }}
        OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      working-directory: 250508/news_clipping
      run: |
        python auto_news_mail.py --mode=github-actions
```

#### 3.2 실행 모드

`auto_news_mail.py`는 다음 모드들을 지원합니다:

- `--mode=github-actions`: GitHub Actions용 실행 (PowerAutomate webhook 전송)
- `--mode=email`: 이메일 전송 모드
- `--mode=teams`: Teams 메시지 생성 모드
- `--reply-to={teams_link}`: Teams 답글 모드

### 4. 데이터 구조

#### 4.1 GitHub Actions에서 PowerAutomate로 전송되는 데이터

```json
{
  "execution_date": "2025-01-27",
  "execution_time": "2025-01-27T08:00:00.000Z",
  "mode": "email",
  "companies_processed": 2,
  "companies": ["삼성", "SK"],
  "total_news_selected": 5,
  "results": {
    "삼성": {
      "news_count": 3,
      "news_items": [
        {
          "title": "삼성전자 실적 발표",
          "date": "01/27",
          "url": "https://...",
          "press": "한국경제"
        }
      ]
    }
  },
  "email_sent": true,
  "email_response": "Success",
  "webhook_sent": true
}
```

### 5. 문제 해결

#### 5.1 일반적인 문제들

1. **GitHub Actions 실행 실패**
   - Secrets이 올바르게 설정되었는지 확인
   - requirements.txt 경로 확인
   - Python 버전 호환성 확인

2. **PowerAutomate 연결 실패**
   - Webhook URL이 올바른지 확인
   - HTTP 요청 형식 확인
   - 네트워크 연결 상태 확인

3. **이메일 전송 실패**
   - 이메일 API 엔드포인트 확인
   - 이메일 크기 제한 확인
   - 인증 정보 확인

#### 5.2 로그 확인

GitHub Actions 실행 로그에서 다음을 확인:

```
====== 자동 뉴스 메일링 시작 ======
GitHub Actions 모드로 실행합니다.
===== 분석 시작: 삼성 =====
...
====== GitHub Actions 결과 출력 ======
PowerAutomate 응답 상태 코드: 200
PowerAutomate로 데이터 전송 성공
GitHub Actions 실행 완료
```

### 6. 보안 고려사항

1. **민감한 정보 보호**
   - API 키와 webhook URL은 반드시 GitHub Secrets에 저장
   - 로그에 민감한 정보가 출력되지 않도록 주의

2. **접근 제어**
   - GitHub repository 접근 권한 관리
   - PowerAutomate flow 권한 설정

3. **모니터링**
   - 실행 실패 시 알림 설정
   - 정기적인 로그 검토

## 추가 기능

### 팀즈 연동
Teams 채널에 메시지를 보내려면:

```python
python auto_news_mail.py --mode=teams
```

### 수동 실행
로컬에서 테스트하려면:

```python
# 이메일 모드로 실행
python auto_news_mail.py --mode=email

# Teams 메시지 생성
python auto_news_mail.py --mode=teams
``` 