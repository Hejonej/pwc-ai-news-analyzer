import json
from urllib.parse import urlparse

# 테스트할 뉴스 데이터 (로그에서 가져온 실제 매거진한경 기사)
test_news = {
    "index": 4, 
    "title": "포스코이앤씨vsHDC현산, 용산 정비창전면 제1구역 '공식 비교표' 전격 공개 - 매거진한경", 
    "url": "https://news.google.com/rss/articles/CBMibEFVX3lxTE1TT2J3c0N4cmNBbDNKTkVVSlJ3enNHNUU2Q0JvQXptMGRzdnBGTjBaeFczdlRnc1JqRi1kTk1JRlRIS3BlcXl2cXpEVlJrZ2w4R1FVUDh3cVgwMlZmQWFuSWE1YjVMYzBVNWh6TQ?oc=5", 
    "date": "Fri, 16 May 2025 23:54:00 GMT", 
    "press": "매거진한경",
    "content": "포스코이앤씨vsHDC현산, 용산 정비창전면 제1구역 '공식 비교표' 전격 공개 - 매거진한경"
}

# 실제 앱에서 사용하는 유효 언론사 설정
valid_press_dict_str = """조선일보: ["조선일보", "chosun", "chosun.com"]
    중앙일보: ["중앙일보", "joongang", "joongang.co.kr", "joins.com"]
    동아일보: ["동아일보", "donga", "donga.com"]
    조선비즈: ["조선비즈", "chosunbiz", "biz.chosun.com"]
    한국경제: ["한국경제", "한경", "hankyung", "hankyung.com", "한경닷컴"]
    매일경제: ["매일경제", "매경", "mk", "mk.co.kr"]
    연합뉴스: ["연합뉴스", "yna", "yna.co.kr"]
    파이낸셜뉴스: ["파이낸셜뉴스", "fnnews", "fnnews.com"]
    데일리팜: ["데일리팜", "dailypharm", "dailypharm.com"]
    IT조선: ["it조선", "it.chosun.com", "itchosun"]
    머니투데이: ["머니투데이", "mt", "mt.co.kr"]
    비즈니스포스트: ["비즈니스포스트", "businesspost", "businesspost.co.kr"]
    이데일리: ["이데일리", "edaily", "edaily.co.kr"]
    아시아경제: ["아시아경제", "asiae", "asiae.co.kr"]
    뉴스핌: ["뉴스핌", "newspim", "newspim.com"]
    뉴시스: ["뉴시스", "newsis", "newsis.com"]
    매거진한경: ["매거진한경", "magazine.hankyung", "magazine.hankyung.com"]
    헤럴드경제: ["헤럴드경제", "herald", "heraldcorp", "heraldcorp.com"]"""

# 유효 언론사 설정 문자열을 딕셔너리로 변환
valid_press_dict = {}
lines = valid_press_dict_str.strip().split('\n')
for line in lines:
    line = line.strip()
    if line and ': ' in line:
        press_name, aliases_str = line.split(':', 1)
        try:
            aliases = eval(aliases_str.strip())
            valid_press_dict[press_name.strip()] = aliases
        except Exception as e:
            print(f"Error parsing line: {line}, Error: {e}")

print("=========== 유효 언론사 설정 ===========")
print(json.dumps(valid_press_dict, indent=2, ensure_ascii=False))

# 필터링 함수 (앱에서 사용하는 코드와 동일)
def check_valid_press(news):
    press = news.get("press", "").lower()
    url = news.get("url", "").lower()
    
    print(f"\n=========== 필터링 체크 ===========")
    print(f"체크할 언론사: {press}")
    print(f"체크할 URL: {url}")
    print(f"URL 도메인: {urlparse(url).netloc}")
    
    # 언론사명이나 URL이 신뢰할 수 있는 언론사 목록에 포함되는지 확인
    is_valid = False
    for main_press, aliases in valid_press_dict.items():
        # 각 별칭 검사 디버깅
        for alias in aliases:
            alias_lower = alias.lower()
            press_match = (alias_lower == press)
            domain = urlparse(url).netloc.lower()
            domain_match = (alias_lower == domain)
            
            if press_match or domain_match:
                print(f"매칭 성공: 언론사 '{main_press}', 별칭 '{alias}'")
                print(f"- 언론사 매칭: {press_match} ('{alias_lower}' == '{press}')")
                print(f"- 도메인 매칭: {domain_match} ('{alias_lower}' == '{domain}')")
                is_valid = True
                break
        
        if is_valid:
            break
    
    if not is_valid:
        print("매칭 실패: 유효한 언론사로 인식되지 않음")
    
    return is_valid

# 디버깅: 매거진한경 기사 테스트
is_valid = check_valid_press(test_news)
print(f"\n최종 결과: {'유효한 언론사' if is_valid else '유효하지 않은 언론사'}")

# 추가 디버깅: 매거진한경 키워드를 명시적으로 확인
print("\n=========== 매거진한경 키워드 명시적 확인 ===========")
for alias in valid_press_dict.get("매거진한경", []):
    print(f"별칭: '{alias}', 소문자: '{alias.lower()}'")
    print(f"언론사와 일치: {alias.lower() == test_news['press'].lower()}")

# 구글 뉴스 URL 분석
print("\n=========== 구글 뉴스 URL 분석 ===========")
google_domain = urlparse(test_news['url']).netloc
print(f"구글 뉴스 도메인: {google_domain}")

# 리다이렉트 URL 시뮬레이션
print("\n=========== 리다이렉트 시뮬레이션 ===========")
# 실제 매거진한경 URL로 가정한 케이스
simulated_url = "https://magazine.hankyung.com/article/123456"
simulated_news = test_news.copy()
simulated_news["url"] = simulated_url

is_valid_with_real_url = check_valid_press(simulated_news)
print(f"\n시뮬레이션 결과: {'유효한 언론사' if is_valid_with_real_url else '유효하지 않은 언론사'}") 