import requests
import json
import os
import traceback
from config import EMAIL_SETTINGS

def send_email(html_body=None, to=None, cc=None, subject=None, importance=None):
    # Apply defaults from config if parameters are not provided
    to = to or EMAIL_SETTINGS["default_to"]
    cc = cc or EMAIL_SETTINGS["default_cc"]
    subject = subject or EMAIL_SETTINGS["default_subject"]
    importance = importance or EMAIL_SETTINGS["importance"]
    
    try:
        # PowerAutomate webhook URL 사용 (이메일 전송도 같은 Flow에서 처리)
        url = os.environ.get('POWERAUTOMATE_WEBHOOK_URL')
        
        if not url:
            raise ValueError("POWERAUTOMATE_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")

        # Use default message if html_body is None
        body_content = html_body if html_body is not None else "테스트테스트"

        # Email data payload
        payload = {
            "to": to,
            "cc": cc,
            "from": EMAIL_SETTINGS["from"],
            "bcc": "",
            "subject": subject,
            "body": body_content,
            "importance": importance
        }

        # Headers
        headers = {
            "Content-Type": "application/json"
        }

        print(f"이메일 전송 시도: {subject} -> {to}")
        print(f"사용 중인 엔드포인트: {url[:50]}...")  # 보안상 일부만 출력
        
        # 디버그용 페이로드 크기 출력
        payload_size = len(json.dumps(payload))
        print(f"페이로드 크기: {payload_size} 바이트")
        
        if payload_size > 1000000:  # 1MB 이상인 경우 경고
            print(f"경고: 페이로드 크기가 큽니다 ({payload_size/1000000:.2f}MB)")
            
            # HTML 내용 크기 줄이기
            if len(body_content) > 500000:
                body_content = body_content[:100000] + "... [내용이 너무 길어서 잘렸습니다] ..."
                payload["body"] = body_content
                print("HTML 내용을 줄였습니다.")

        # Send POST request (timeout 설정)
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=30)

        # Print response
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:200]}..." if len(response.text) > 200 else f"Response: {response.text}")

        # Check if successful
        if response.status_code >= 200 and response.status_code < 300:
            print("Email request sent successfully!")
            return True, response
        else:
            print(f"Failed to send email request. Status code: {response.status_code}")
            return False, response
            
    except requests.Timeout:
        error_msg = "API 요청 시간이 초과되었습니다."
        print(error_msg)
        return False, {"error": error_msg, "status_code": "Timeout"}
        
    except requests.ConnectionError:
        error_msg = "네트워크 연결 오류가 발생했습니다."
        print(error_msg)
        return False, {"error": error_msg, "status_code": "ConnectionError"}
        
    except Exception as e:
        error_msg = f"이메일 전송 중 오류 발생: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        return False, {"error": error_msg, "status_code": "Exception", "exception": str(e)}

if __name__ == "__main__":
    # Test function when module is run directly
    try:
        test_result, test_response = send_email("테스트 HTML 내용입니다.")
        print(f"테스트 결과: {'성공' if test_result else '실패'}")
    except Exception as e:
        print(f"테스트 중 예외 발생: {str(e)}")
        print(traceback.format_exc())
