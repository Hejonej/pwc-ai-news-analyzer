from typing import List, Dict, Any, TypedDict
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from googlenews import GoogleNews
import operator
import dotenv
import json
import re
import os
from datetime import datetime, timedelta, timezone
import streamlit as st
import time


import dotenv #pwc
dotenv.load_dotenv(override=True) #pwc

# 한국 시간대(KST) 정의
KST = timezone(timedelta(hours=9))

# 상태 타입 정의
class AgentState(TypedDict):
    news_data: List[dict]
    filtered_news: List[dict]
    analysis: str
    keyword: str
    system_prompt: str
    user_prompt: str
    excluded_news: List[dict]
    borderline_news: List[dict]
    retained_news: List[dict]
    grouped_news: List[dict]
    final_selection: List[dict]
    system_prompt_1: str
    user_prompt_1: str
    llm_response_1: str
    system_prompt_2: str
    user_prompt_2: str
    llm_response_2: str
    system_prompt_3: str
    user_prompt_3: str
    llm_response_3: str
    not_selected_news: List[dict]
    original_news_data: List[dict]
    start_datetime: datetime
    end_datetime: datetime

# 신뢰할 수 있는 언론사 목록 (기본값으로만 사용)
TRUSTED_PRESS_ALIASES = {
    "조선일보": ["조선일보", "chosun", "chosun.com"],
    "중앙일보": ["중앙일보", "joongang", "joongang.co.kr", "joins.com"],
    "동아일보": ["동아일보", "donga", "donga.com"],
    "조선비즈": ["조선비즈", "chosunbiz", "biz.chosun.com"],
    "한국경제": ["한국경제", "한경", "hankyung", "hankyung.com", "한경닷컴"],
    "매일경제": ["매일경제", "매경", "mk", "mk.co.kr"],
    "연합뉴스": ["연합뉴스", "yna", "yna.co.kr"],
    "파이낸셜뉴스": ["파이낸셜뉴스", "fnnews", "fnnews.com"],
    "데일리팜": ["데일리팜", "dailypharm", "dailypharm.com"],
    "IT조선": ["it조선", "it.chosun.com", "itchosun"],
    "머니투데이": ["머니투데이", "mt", "mt.co.kr"],
    "비즈니스포스트": ["비즈니스포스트", "businesspost", "businesspost.co.kr"],
    "이데일리": ["이데일리", "edaily", "edaily.co.kr"],
    "아시아경제": ["아시아경제", "asiae", "asiae.co.kr"],
    "뉴스핌": ["뉴스핌", "newspim", "newspim.com"],
    "뉴시스": ["뉴시스", "newsis", "newsis.com"],
    "헤럴드경제": ["헤럴드경제", "herald", "heraldcorp", "heraldcorp.com"]
}

# 헬퍼 함수: LLM 호출
def call_llm(state: AgentState, system_prompt: str, user_prompt: str, stage: int = 1) -> str:
    """LLM을 호출하고 응답을 반환하는 함수"""
    try:
        # LLM 초기화
        llm = ChatOpenAI(
            #openai_api_key=os.getenv("OPENAI_API_KEY"), #Test
            #openai_api_base=os.getenv("OPENAI_BASE_URL"), #Test
            #model_name = "openai.gpt-4.1-2025-04-14", #Test
            model_name=state.get("model", "gpt-4o"), #Test
            temperature=0.1,
            #max_tokens=2000
        )

        # 메시지 구성
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]

        # 프롬프트 저장
        if stage == 1:
            state["system_prompt_1"] = system_prompt
            state["user_prompt_1"] = user_prompt
        elif stage == 2:
            state["system_prompt_2"] = system_prompt
            state["user_prompt_2"] = user_prompt
        elif stage == 3:
            state["system_prompt_3"] = system_prompt
            state["user_prompt_3"] = user_prompt

        # 디버그 출력
        print(f"\n=== {stage}단계: 프롬프트 ===")
        print("\n[System Prompt]:")
        print(system_prompt)
        print("\n[User Prompt]:")
        print(user_prompt)

        # LLM 호출
        result = llm.invoke(messages).content
        
        # 응답 저장
        if stage == 1:
            state["llm_response_1"] = result
        elif stage == 2:
            state["llm_response_2"] = result
        elif stage == 3:
            state["llm_response_3"] = result
            
        print(f"\n=== {stage}단계: LLM 응답 ===")
        print(result)
        
        return result
    
    except Exception as e:
        st.error(f"LLM 호출 중 오류가 발생했습니다: {str(e)}")
        return ""

# 헬퍼 함수: JSON 파싱
def parse_json_response(response: str) -> dict:
    """LLM 응답에서 JSON을 추출하고 파싱하는 함수"""
    try:
        # 코드 블록 제거
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            # 첫 줄 제거 (```json 또는 ``` 제거)
            response = "\n".join(response.split("\n")[1:])
        if response.endswith("```"):
            # 마지막 줄 제거
            response = "\n".join(response.split("\n")[:-1])
        
        # 앞뒤 공백 제거
        response = response.strip()
        
        # JSON 시작/끝 확인
        if not response.startswith("{"):
            response = "{" + response
        if not response.endswith("}"):
            response = response + "}"
        
        # 중괄호 쌍이 맞는지 확인
        open_braces = response.count("{")
        close_braces = response.count("}")
        if open_braces > close_braces:
            response = response + "}" * (open_braces - close_braces)
        elif close_braces > open_braces:
            response = "{" * (close_braces - open_braces) + response
        
        # JSON 파싱
        return json.loads(response)
    
    except json.JSONDecodeError as e:
        print(f"JSON 파싱 오류: {str(e)}")
        print(f"원본 응답: {response}")
        raise e

# 뉴스 수집기 함수
def collect_news(state: AgentState) -> AgentState:
    """뉴스를 수집하는 함수"""
    try:
        # 검색어 설정 - 문자열 또는 리스트 처리
        keyword = state.get("keyword", "삼성")
        
        # 검색 결과 수는 항상 100개
        max_results = 100
        
        # 날짜 범위 가져오기
        start_datetime = state.get("start_datetime")
        end_datetime = state.get("end_datetime")
        
        # GoogleNews 객체 생성
        news = GoogleNews()
        
        # keyword가 문자열이면 리스트로 변환, 아니면 그대로 사용
        if isinstance(keyword, str):
            keywords_to_search = [keyword]
        else:
            keywords_to_search = keyword
        
        # 모든 키워드에 대한 뉴스 수집
        all_news_data = []
        
        # 각 키워드별로 뉴스 검색 및 결과 병합
        for kw in keywords_to_search:
            print(f"키워드 '{kw}' 검색 중...")
            news_results = news.search_by_keyword(kw, k=max_results)
            all_news_data.extend(news_results)
            print(f"키워드 '{kw}' 검색 결과: {len(news_results)}개")
        
        # 중복 URL 제거 (같은 URL이면 중복으로 간주)
        unique_urls = set()
        unique_news_data = []
        
        for news_item in all_news_data:
            url = news_item.get('url', '')
            if url and url not in unique_urls:
                unique_urls.add(url)
                unique_news_data.append(news_item)
        
        print(f"중복 제거 후 전체 뉴스 수: {len(unique_news_data)}개")
        
        # 날짜 필터링
        if start_datetime and end_datetime:
            print(f"\n=== 날짜 필터링 시작 ===")
            print(f"필터링 범위: {start_datetime} ~ {end_datetime}")
            
            filtered_news = []
            date_parsing_stats = {
                "total": len(unique_news_data),
                "no_date": 0,
                "parse_success": 0,
                "parse_failed": 0,
                "in_range": 0,
                "out_of_range": 0
            }
            
            for news_item in unique_news_data:
                try:
                    # 뉴스 날짜 파싱
                    news_date_str = news_item.get('date', '')
                    if not news_date_str:
                        date_parsing_stats["no_date"] += 1
                        # 날짜 정보가 없는 뉴스는 포함 (최신 뉴스일 가능성)
                        filtered_news.append(news_item)
                        continue
                    
                    news_date = None
                    
                    # 다양한 날짜 형식 처리 (우선순위 순)
                    date_formats = [
                        '%a, %d %b %Y %H:%M:%S %Z',      # GMT 형식: Mon, 01 Jan 2024 12:00:00 GMT
                        '%a, %d %b %Y %H:%M:%S GMT',     # GMT 형식 (명시적)
                        '%Y-%m-%d %H:%M:%S',             # YYYY-MM-DD HH:MM:SS
                        '%Y-%m-%d',                      # YYYY-MM-DD
                        '%Y년 %m월 %d일',                # 한국어 형식
                        '%m/%d/%Y',                      # MM/DD/YYYY
                        '%d/%m/%Y',                      # DD/MM/YYYY
                        '%Y.%m.%d',                      # YYYY.MM.DD
                        '%m.%d.%Y',                      # MM.DD.YYYY
                    ]
                    
                    for date_format in date_formats:
                        try:
                            news_date = datetime.strptime(news_date_str, date_format)
                            break
                        except ValueError:
                            continue
                    
                    if news_date is None:
                        date_parsing_stats["parse_failed"] += 1
                        print(f"날짜 파싱 실패: '{news_date_str}' - 포함하여 처리")
                        # 파싱 실패한 뉴스도 포함 (최신 뉴스일 가능성)
                        filtered_news.append(news_item)
                        continue
                    
                    date_parsing_stats["parse_success"] += 1
                    
                    # GMT 시간대 변환 전 날짜 기록
                    original_news_date = news_date
                    
                    # 시간대 처리: GMT 시간을 한국 시간(KST)으로 변환
                    if 'GMT' in news_date_str or 'Z' in news_date_str:
                        # GMT 시간에 9시간 추가하여 KST로 변환
                        news_date = news_date + timedelta(hours=9)
                        # 첫 몇 개 뉴스에 대해서만 변환 정보 출력
                        if date_parsing_stats["parse_success"] <= 3:
                            print(f"GMT→KST 변환: {original_news_date} → {news_date}")
                    
                    # 파싱된 날짜에 KST 시간대 추가 (시간대가 없는 경우)
                    if news_date.tzinfo is None:
                        news_date = news_date.replace(tzinfo=KST)
                    
                    # 시간까지 고려한 정확한 범위 체크 (08:00 기준)
                    if start_datetime <= news_date <= end_datetime:
                        date_parsing_stats["in_range"] += 1
                        filtered_news.append(news_item)
                    else:
                        date_parsing_stats["out_of_range"] += 1
                        # 범위 외 뉴스 중 첫 몇 개만 출력
                        if date_parsing_stats["out_of_range"] <= 3:
                            print(f"시간 범위 외: {news_date} (범위: {start_datetime} ~ {end_datetime})")
                        
                except Exception as e:
                    date_parsing_stats["parse_failed"] += 1
                    print(f"날짜 처리 오류: {e} - 뉴스 포함하여 처리")
                    # 오류 발생한 뉴스도 포함
                    filtered_news.append(news_item)
                    continue
            
            unique_news_data = filtered_news
            
            # 날짜 필터링 통계 출력
            print(f"\n=== 날짜 필터링 통계 ===")
            print(f"전체 뉴스: {date_parsing_stats['total']}개")
            print(f"날짜 정보 없음: {date_parsing_stats['no_date']}개")
            print(f"날짜 파싱 성공: {date_parsing_stats['parse_success']}개")
            print(f"날짜 파싱 실패: {date_parsing_stats['parse_failed']}개")
            print(f"날짜 범위 내: {date_parsing_stats['in_range']}개")
            print(f"날짜 범위 외: {date_parsing_stats['out_of_range']}개")
            print(f"최종 필터링된 뉴스: {len(unique_news_data)}개")
        
        # 원래 인덱스 추가
        for i, news_item in enumerate(unique_news_data, 1):
            news_item['original_index'] = i
        
        # 원본 뉴스 데이터 저장
        state["original_news_data"] = unique_news_data.copy()
        # 필터링할 뉴스 데이터 저장
        state["news_data"] = unique_news_data
        
        # 날짜 필터링 결과 출력
        print(f"\n날짜 필터링 결과:")
        print(f"시작 날짜: {start_datetime}")
        print(f"종료 날짜: {end_datetime}")
        print(f"필터링된 뉴스 수: {len(unique_news_data)}")
        
        return state
    except Exception as e:
        print(f"뉴스 수집 중 오류 발생: {e}")
        return state

def filter_valid_press(state: AgentState) -> AgentState:
    """유효 언론사 필터링"""
    news_data = state.get("news_data", [])
    
    # UI에서 설정한 유효 언론사 목록 가져오기
    valid_press_dict_str = state.get("valid_press_dict", "")
    
    # UI 설정 값이 문자열이면 딕셔너리로 파싱
    valid_press_config = {}
    if isinstance(valid_press_dict_str, str) and valid_press_dict_str.strip():
        #print("\n[DEBUG] UI에서 설정한 언론사 문자열 파싱 시작")
        try:
            # 문자열에서 딕셔너리 파싱
            lines = valid_press_dict_str.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line and ': ' in line:
                    press_name, aliases_str = line.split(':', 1)
                    try:
                        # 문자열 형태의 리스트를 실제 리스트로 변환
                        aliases = eval(aliases_str.strip())
                        valid_press_config[press_name.strip()] = aliases
                        print(f"[DEBUG] 파싱 성공: {press_name.strip()} -> {aliases}")
                    except Exception as e:
                        print(f"[DEBUG] 파싱 실패: {line}, 오류: {str(e)}")
        except Exception as e:
            print(f"[DEBUG] 전체 파싱 실패: {str(e)}")
    # UI 설정 값이 이미 딕셔너리면 그대로 사용
    elif isinstance(valid_press_dict_str, dict):
        valid_press_config = valid_press_dict_str
        #print("\n[DEBUG] UI에서 설정한 언론사 딕셔너리 직접 사용")
    
    # 파싱 결과가 비어있으면 기본값 사용
    if not valid_press_config:
        #print("\n[DEBUG] 유효한 설정을 찾을 수 없어 기본값 사용")
        valid_press_config = TRUSTED_PRESS_ALIASES
    
    print(f"\n전체 수집된 뉴스 수: {len(news_data)}")
    
    # 카테고리별 제외 언론사 별칭 가져오기 (선택적으로 전달됨)
    excluded_press_aliases = state.get("excluded_press_aliases", {})
    # 정규화된 제외 별칭 리스트 미리 구성 (URL 부분 일치 허용)
    normalized_excluded_aliases = []
    for aliases in excluded_press_aliases.values():
        for alias in aliases:
            normalized_excluded_aliases.append(re.sub(r'\s+', ' ', alias.lower().strip()))
    print(f"\n=== 유효 언론사 설정 ===")
    for press, aliases in valid_press_config.items():
        print(f"- {press}: {aliases}")
    
    # 문자열 정규화 함수
    def normalize_string(s):
        """문자열을 정규화하여 비교하기 쉽게 만듭니다."""
        if not s:
            return ""
        # 소문자로 변환, 선행/후행 공백 제거, 연속된 공백을 하나로 변환
        return re.sub(r'\s+', ' ', s.lower().strip())
    
    # 유효 언론사 뉴스 필터링 함수
    def filter_news(news_list):
        valid_news = []
        for i, news in enumerate(news_list):
            # 원본 데이터 저장
            original_press = news.get("press", "")
            original_url = news.get("url", "")
            
            # 정규화된 값 생성
            press = normalize_string(original_press)
            url = normalize_string(original_url)
            
            #print(f"\n=== 뉴스 #{i+1} 필터링 검사 ===")
            #print(f"제목: {news.get('content', '제목 없음')}")
            #print(f"언론사: '{original_press}' (정규화: '{press}')")
            #print(f"URL: {original_url}")
            
            # 언론사명이 신뢰할 수 있는 언론사 목록에 포함되는지 확인
            is_valid = False
            matched_press = None
            matched_alias = None
            
            for main_press, aliases in valid_press_config.items():
                # 별칭들도 정규화
                normalized_aliases = [normalize_string(alias) for alias in aliases]
                
                # 언론사명 매칭 검사 - 완전 일치 우선, 그 다음 포함 관계 확인
                for alias in normalized_aliases:
                    # 완전 일치 우선
                    if press == alias:
                        matched_press = main_press
                        matched_alias = alias
                        print(f"✓ 언론사명 완전 매칭 성공: '{press}' == '{alias}' (언론사: {main_press})")
                        is_valid = True
                        break
                    # 길이가 3자 이상일 때만 포함 관계 확인 (짧은 별칭으로 인한 오매칭 방지)
                    elif len(alias) >= 3 and len(press) >= 3:
                        if press in alias or alias in press:
                            matched_press = main_press
                            matched_alias = alias
                            print(f"✓ 언론사명 포함 매칭 성공: '{press}' 매칭됨 '{alias}' (언론사: {main_press})")
                            is_valid = True
                            break
                
                if is_valid:
                    break
            
            # Financial 카테고리 등에서 제외해야 하는 언론사면 제거
            if is_valid:
                # 제외 목록과 매칭되는지 확인 (press와 url에 대한 부분 일치 포함)
                is_excluded_press = False
                for ex_alias in normalized_excluded_aliases:
                    if len(ex_alias) >= 3 and (ex_alias in press or ex_alias in url):
                        is_excluded_press = True
                        break
                if is_excluded_press:
                    print(f"✗ 제외 언론사 매칭되어 제거: press='{original_press}', url='{original_url}'")
                    continue
                #print(f"✅ 결과: 유효한 언론사 '{matched_press}'로 인식됨 (매칭된 별칭: '{matched_alias}')")
                # 매칭된 정보 추가
                news["matched_press"] = matched_press
                news["matched_alias"] = matched_alias
                valid_news.append(news)
            #else:
                #print(f"❌ 결과: 유효하지 않은 언론사로 인식됨")
                # 실패한 경우 상세 로그
                #print(f"[DEBUG] 실패 세부 정보 - 언론사: '{press}'")
                #print(f"[DEBUG] 사용 중인 유효 언론사 목록의 키: {list(valid_press_config.keys())}")
        
        return valid_news
    
    # 모든 뉴스를 한 번에 처리
    valid_press_news = filter_news(news_data)
    print(f"\n유효 언론사 뉴스 수: {len(valid_press_news)}")
    
    # 정리된 결과 출력
    print("\n=== 유효 언론사별 필터링 결과 ===")
    press_count = {}
    for news in valid_press_news:
        matched_press = news.get("matched_press", "알 수 없음")
        if matched_press in press_count:
            press_count[matched_press] += 1
        else:
            press_count[matched_press] = 1
    
    for press, count in press_count.items():
        print(f"- {press}: {count}개 기사")
    
    # 유효 언론사 뉴스가 없는 경우
    if not valid_press_news:
        print("유효 언론사의 뉴스가 없습니다.")
        state["news_data"] = []
        return state
    
    # state 업데이트
    state["news_data"] = valid_press_news
    return state

def filter_excluded_keywords(state: AgentState) -> AgentState:
    """Rule 기반 키워드 필터링 - 특정 키워드가 포함된 기사 제외"""
    news_data = state.get("news_data", [])
    
    # config.py에서 제외할 키워드 목록 가져오기 (동적으로 처리)
    # auto_news_mail.py나 app.py에서 호출될 때 사용할 수 있도록 기본값 제공
    # 수정된 코드
    excluded_keywords = state.get("excluded_keywords", [])
    if not excluded_keywords:
        print(f"\n=== Rule 기반 키워드 필터링 건너뛰기 ===")
        print("제외할 키워드가 설정되지 않았습니다.")
        return state

    print(f"\n=== Rule 기반 키워드 필터링 ===")
    print(f"필터링 전 뉴스 수: {len(news_data)}")
    print(f"제외 키워드: {excluded_keywords}")
    
    filtered_news = []
    excluded_by_keywords = []
    
    for news in news_data:
        title = news.get("content", "")
        
        # 제목에서 제외 키워드 검색
        is_excluded = False
        matched_keyword = ""
        
        for keyword in excluded_keywords:
            if keyword in title:
                is_excluded = True
                matched_keyword = keyword
                break
        
        if is_excluded:
            excluded_by_keywords.append({
                "title": title,
                "url": news.get("url", ""),
                "matched_keyword": matched_keyword,
                "press": news.get("press", "알 수 없음")
            })
        else:
            filtered_news.append(news)
    
    print(f"필터링 후 뉴스 수: {len(filtered_news)}")
    print(f"키워드로 제외된 뉴스 수: {len(excluded_by_keywords)}")
    
    # 제외된 뉴스 로그 출력
    if excluded_by_keywords:
        print(f"\n=== 키워드로 제외된 뉴스 목록 ===")
        for i, excluded in enumerate(excluded_by_keywords, 1):
            print(f"{i}. [{excluded['matched_keyword']}] {excluded['title']}")
            print(f"   언론사: {excluded['press']}")
            print(f"   URL: {excluded['url']}")
    
    # state 업데이트
    state["news_data"] = filtered_news
    # 제외된 뉴스 정보도 저장 (디버깅용)
    state["excluded_by_keywords"] = excluded_by_keywords
    
    return state

# 1단계: 뉴스 제외 판단
def filter_excluded_news(state: AgentState) -> AgentState:
    """뉴스를 제외/보류/유지로 분류하는 함수"""
    try:
        # 시스템 프롬프트 설정
        system_prompt = state.get("system_prompt_1", "당신은 회계법인의 뉴스 분석 전문가입니다. 뉴스의 중요성을 판단하여 제외/보류/유지로 분류하는 작업을 수행합니다. 특히 회계법인의 관점에서 중요하지 않은 뉴스(예: 단순 홍보, CSR 활동, 이벤트 등)를 식별하고, 회계 감리나 재무 관련 이슈는 반드시 유지하도록 합니다.")
        
        # 뉴스 데이터 준비
        news_data = state.get("news_data", [])
        if not news_data:
            st.error("분석할 뉴스가 없습니다.")
            return state
            
        # 뉴스 목록 문자열 생성 - 원래 인덱스 사용
        news_list = ""
        for news in news_data:
            press = news.get('press', '알 수 없음')
            original_index = news.get('original_index')
            news_list += f"{original_index}. {news['content']} ({press})\n"
            
        # 제외 판단 프롬프트
        exclusion_prompt = f"""아래 뉴스 목록을 회계법인의 관점에서 분석하여 제외/보류/유지로 분류해주세요.
각 뉴스의 번호는 고유 식별자이므로 변경하지 말고 그대로 응답에 사용해주세요.

[뉴스 목록]
{news_list}

[제외 기준]
{state.get("exclusion_criteria", "")}

[응답 요구사항]
1. 제외/보류/유지 사유는 간단명료하게 작성
2. 각 카테고리별 최대 20개까지만 포함
3. 응답은 완전한 JSON 형식이어야 함

다음과 같은 JSON 형식으로 응답해주세요:
{{
  "excluded": [
    {{
      "index": 1,
      "title": "뉴스 제목",
      "reason": "제외 사유"
    }}
  ],
  "borderline": [
    {{
      "index": 2,
      "title": "뉴스 제목",
      "reason": "보류 사유"
    }}
  ],
  "retained": [
    {{
      "index": 3,
      "title": "뉴스 제목",
      "reason": "유지 사유"
    }}
  ]
}}"""

        # 최대 3번까지 시도
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # LLM 호출 (헬퍼 함수 사용)
                result = call_llm(state, system_prompt, exclusion_prompt, stage=1)
                
                # JSON 파싱 (헬퍼 함수 사용)
                classification = parse_json_response(result)
                
                # 필수 필드 확인
                if not all(key in classification for key in ["excluded", "borderline", "retained"]):
                    raise ValueError("필수 필드가 누락되었습니다.")
                
                # 상태 업데이트 시 원래 인덱스 유지
                for category in ["excluded", "borderline", "retained"]:
                    for item in classification.get(category, []):
                        original_index = item['index']
                        item['original_index'] = original_index
                
                state["excluded_news"] = classification.get("excluded", [])
                state["borderline_news"] = classification.get("borderline", [])
                state["retained_news"] = classification.get("retained", [])
                
                print("\n[분류 결과]")
                print(f"제외: {len(state['excluded_news'])}개")
                print(f"보류: {len(state['borderline_news'])}개")
                print(f"유지: {len(state['retained_news'])}개")
                
                # 성공적으로 파싱되면 루프 종료
                break
                
            except (json.JSONDecodeError, ValueError) as e:
                print(f"\n파싱 시도 {attempt + 1} 실패: {str(e)}")
                if attempt == max_retries - 1:  # 마지막 시도에서도 실패
                    st.error(f"분류 결과 파싱 중 오류가 발생했습니다: {str(e)}")
                    return state
                # 다음 시도를 위해 잠시 대기
                time.sleep(1)

        return state

    except Exception as e:
        st.error(f"뉴스 분류 중 오류가 발생했습니다: {str(e)}")
        return state

# 2단계: 뉴스 그룹핑 + 대표 기사 선택
def group_and_select_news(state: AgentState) -> AgentState:
    try:
        # 디버깅 정보 출력
        print("\n=== 그룹핑 전 인덱스 정보 ===")
        print(f"보류 뉴스 인덱스: {[news['index'] for news in state['borderline_news']]}")
        print(f"유지 뉴스 인덱스: {[news['index'] for news in state['retained_news']]}")

        # 유지 및 보류 뉴스 합치기
        retained_indices = [news["index"] for news in state["retained_news"]]
        borderline_indices = [news["index"] for news in state["borderline_news"]]
        target_indices = retained_indices + borderline_indices
        
        print(f"대상 뉴스 인덱스: {target_indices}")
        
        # 대상 뉴스 필터링 (원래 인덱스 매핑)
        target_news = []
        for news in state["news_data"]:
            original_index = news.get("original_index")
            if original_index in target_indices:
                print(f"매칭된 뉴스: index={original_index}, title={news['content']}")
                news["current_index"] = original_index  # current_index에 original_index 저장
                target_news.append(news)
        
        print(f"필터링된 대상 뉴스 수: {len(target_news)}")
        
        if not target_news:
            print("필터링된 뉴스가 없습니다!")
            return state

        # 뉴스 데이터를 문자열로 변환 (current_index 사용)
        news_text = "\n\n".join([
            f"인덱스: {news['current_index']}\n제목: {news['content']}\n언론사: {news.get('press', '알 수 없음')}\n발행일: {news.get('date', '알 수 없음')}"
            for news in target_news
        ])

        # 그룹핑 프롬프트
        system_prompt = state.get("system_prompt_2", "당신은 뉴스 분석 전문가입니다. 유사한 뉴스를 그룹화하고 대표성을 갖춘 기사를 선택하는 작업을 수행합니다. 같은 사안에 대해 숫자, 기업 ,계열사, 맥락, 주요 키워드 등이 유사하면 중복으로 판단합니다. 언론사의 신뢰도와 기사의 상세도를 고려하여 대표 기사를 선정합니다.")
        
        grouping_prompt = f"""유사한 뉴스끼리 그룹으로 묶고, 각 그룹에서 가장 대표성 있는 뉴스 1건만 선택해 주세요.
주어진 인덱스 번호를 정확히 사용해주세요. 인덱스 번호를 임의로 변경하지 마세요.

[뉴스 목록]
{news_text}

[중복 처리 기준]
{state.get("duplicate_handling", "")}

다음과 같은 JSON 형식으로 응답해주세요:
{{
  "groups": [
    {{
      "indices": [2, 4],
      "selected_index": 2,
      "reason": "동일한 회원권 관련 보도이며, 2번이 더 자세하고 언론사 우선순위가 높음"
    }},
    {{
      "indices": [5],
      "selected_index": 5,
      "reason": "단독 기사"
    }}
  ]
}}"""

        try:
            # LLM 호출 (헬퍼 함수 사용)
            result = call_llm(state, system_prompt, grouping_prompt, stage=2)
            
            # JSON 파싱 (헬퍼 함수 사용)
            grouping = parse_json_response(result)
            grouped_news = grouping.get("groups", [])
            
            # 그룹핑된 뉴스의 인덱스들을 모두 수집
            grouped_indices = set()
            for group in grouped_news:
                grouped_indices.update(group.get("indices", []))
            
            # 그룹핑되지 않은 뉴스들을 찾아서 각각 단일 그룹으로 추가
            current_indices = set(news["current_index"] for news in target_news)
            ungrouped_indices = current_indices - grouped_indices
            
            # 미그룹 뉴스들을 각각 단일 그룹으로 추가
            for idx in ungrouped_indices:
                new_group = {
                    "indices": [idx],
                    "selected_index": idx,
                    "reason": "개별 뉴스로 처리"
                }
                grouped_news.append(new_group)
            
            # 그룹핑 결과 저장
            state["grouped_news"] = grouped_news
            
            # 디버깅 정보 출력
            print("\n=== 그룹핑 결과 ===")
            for group in grouped_news:
                print(f"그룹: {group['indices']}, 선택된 인덱스: {group['selected_index']}")
            
            return state

        except json.JSONDecodeError as e:
            st.error(f"그룹핑 결과 파싱 중 오류가 발생했습니다: {str(e)}")
            return state

    except Exception as e:
        st.error(f"뉴스 그룹핑 중 오류가 발생했습니다: {str(e)}")
        return state

# 3단계: 중요도 평가 + 최종 선정
def evaluate_importance(state: AgentState) -> AgentState:
    try:
        # 선택된 뉴스 추출
        selected_news = []
        index_map = {}  # 리스트 인덱스와 원래 인덱스 간의 매핑
        
        # 디버깅 정보 출력
        print("\n=== 중요도 평가 시작 ===")
        print(f"그룹 수: {len(state['grouped_news'])}")
        
        # 각 그룹에서 선택된 뉴스 찾기
        for i, group in enumerate(state["grouped_news"], 1):
            selected_index = group["selected_index"]
            
            # 원래 뉴스 데이터에서 selected_index와 일치하는 뉴스 찾기
            selected_article = next(
                (news for news in state["news_data"] 
                 if news.get("original_index") == selected_index),
                None
            )
            
            if selected_article:
                print(f"그룹 {i}, 선택된 인덱스 {selected_index}: 제목 = {selected_article['content']}")
                # 리스트 인덱스를 i로, 원래 인덱스를 selected_index로 매핑
                index_map[i] = selected_index
                selected_article["list_index"] = i
                selected_article["group_info"] = group
                selected_news.append(selected_article)
            else:
                print(f"그룹 {i}, 선택된 인덱스 {selected_index}: 해당 뉴스를 찾을 수 없음")
        
        if not selected_news:
            print("선택된 뉴스가 없습니다!")
            return state

        # 뉴스 데이터를 문자열로 변환 (list_index 사용)
        news_text = "\n\n".join([
            f"인덱스: {news['list_index']}\n제목: {news['content']}\n언론사: {news.get('press', '알 수 없음')}\n발행일: {news.get('date', '알 수 없음')}"
            for news in selected_news
        ])

        # 중요도 평가 프롬프트
        system_prompt = state.get("system_prompt_3", "당신은 회계법인의 전문 애널리스트입니다. 뉴스의 중요도를 평가하고 최종 선정하는 작업을 수행합니다. 특히 회계 감리, 재무제표, 경영권 변동, 주요 계약, 법적 분쟁 등 회계법인의 관점에서 중요한 이슈를 식별하고, 그 중요도를 '상' 또는 '중'으로 평가합니다. 또한 각 뉴스의 핵심 키워드와 관련 계열사를 식별하여 보고합니다.")
        
        evaluation_prompt = f"""아래 기사들에 대해 회계법인의 시각으로 중요도를 평가하고, 모든 뉴스에 대해 평가 결과를 알려주세요.
중요도 '상' 또는 '중'인 뉴스는 최종 선정하고, '하'인 뉴스는 선정하지 않습니다.

[뉴스 목록]
{news_text}

[선택 기준]
{state.get("selection_criteria", "")}

[응답 요구사항]
1. 중요도는 "상", "중", "하" 중 하나로 평가
2. 미선정 사유는 간단명료하게 작성
3. 응답은 완전한 JSON 형식이어야 함

다음과 같은 JSON 형식으로 응답해주세요:
{{
  "final_selection": [
        {{
            "index": 2,
            "title": "뉴스 제목",
            "importance": "상",
            "reason": "선정 사유",
            "keywords": ["키워드1", "키워드2"],
            "affiliates": ["계열사1", "계열사2"],
            "press": "언론사명",
            "date": "발행일"
        }}
  ],
  "not_selected": [
    {{
      "index": 3,
      "title": "뉴스 제목",
      "importance": "하",
      "reason": "미선정 사유"
    }}
  ]
}}"""

        # 최대 3번까지 시도
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # LLM 호출 (헬퍼 함수 사용)
                result = call_llm(state, system_prompt, evaluation_prompt, stage=3)
                
                # JSON 파싱 (헬퍼 함수 사용)
                evaluation = parse_json_response(result)
                
                # 필수 필드 확인
                if not all(key in evaluation for key in ["final_selection", "not_selected"]):
                    raise ValueError("필수 필드가 누락되었습니다.")
                
                # 최종 선정된 뉴스 처리
                for news in evaluation["final_selection"]:
                    list_index = news["index"]
                    if list_index in index_map:
                        original_index = index_map[list_index]
                        original_news = next(
                            (n for n in selected_news if n["list_index"] == list_index),
                            None
                        )
                        if original_news:
                            # 원본 데이터의 메타데이터를 그대로 사용
                            news.update({
                                "url": original_news.get("url", ""),
                                "press": original_news.get("press", ""),  # LLM이 제공한 press 대신 원본 press 사용
                                "date": original_news.get("date", ""),
                                "original_index": original_index,
                                "group_info": original_news["group_info"]
                            })
                            print(f"최종 선정 뉴스: 인덱스={original_index}, 제목={news['title']}")

                # 미선정 뉴스도 동일하게 처리
                for news in evaluation["not_selected"]:
                    list_index = news["index"]
                    if list_index in index_map:
                        original_index = index_map[list_index]
                        original_news = next(
                            (n for n in selected_news if n["list_index"] == list_index),
                            None
                        )
                        if original_news:
                            news.update({
                                "url": original_news.get("url", ""),
                                "press": original_news.get("press", ""),  # LLM이 제공한 press 대신 원본 press 사용
                                "date": original_news.get("date", ""),
                                "original_index": original_index,
                                "group_info": original_news["group_info"]
                            })
                            print(f"미선정 뉴스: 인덱스={original_index}, 제목={news['title']}")
                
                state["final_selection"] = evaluation.get("final_selection", [])
                state["not_selected_news"] = evaluation.get("not_selected", [])
                
                print(f"최종 선정 뉴스 수: {len(state['final_selection'])}")
                print(f"미선정 뉴스 수: {len(state['not_selected_news'])}")
                
                return state

            except (json.JSONDecodeError, ValueError) as e:
                print(f"\n파싱 시도 {attempt + 1} 실패: {str(e)}")
                if attempt == max_retries - 1:  # 마지막 시도에서도 실패
                    st.error(f"중요도 평가 결과 파싱 중 오류가 발생했습니다: {str(e)}")
                    return state
                # 다음 시도를 위해 잠시 대기
                time.sleep(1)

        return state

    except Exception as e:
        st.error(f"중요도 평가 중 오류가 발생했습니다: {str(e)}")
        return state


# 노드 정의
def get_nodes():
    return {
        "collect_news": collect_news,
        "filter_valid_press": filter_valid_press,
        "filter_excluded_news": filter_excluded_news,
        "group_and_select_news": group_and_select_news,
        "evaluate_importance": evaluate_importance
    }

# 에지 정의
def get_edges():
    return [
        ("collect_news", "filter_valid_press"),
        ("filter_valid_press", "filter_excluded_news"),
        ("filter_excluded_news", "group_and_select_news"),
        ("group_and_select_news", "evaluate_importance"),
        ("evaluate_importance", END)
    ]

# 뉴스 출력 함수
def print_news(news_list, title):
    print(f"\n=== {title} ===")
    for i, news in enumerate(news_list):
        print(f"\n[{i+1}] 제목: {news['content']}")
        print(f"    URL: {news['url']}")

# 메인 실행 함수
def main():
    # 노드 및 에지 가져오기
    nodes = get_nodes()
    edges = get_edges()
    
    # 그래프 생성
    builder = StateGraph(AgentState)
    
    # 노드 추가
    for node_name, node_fn in nodes.items():
        builder.add_node(node_name, node_fn)
    
    # 에지 추가
    for start, end in edges:
        builder.add_edge(start, end)
    
    # 시작점 설정
    builder.set_entry_point("collect_news")
    
    # 그래프 컴파일
    graph = builder.compile()
    
    # 실행
    # 빈 초기 상태로 시작
    result = graph.invoke({
        "news_data": [],
        "filtered_news": [],
        "analysis": "",
        "keyword": "삼성전자",
        "system_prompt": "",
        "user_prompt": "",
        "excluded_news": [],
        "borderline_news": [],
        "retained_news": [],
        "grouped_news": [],
        "final_selection": [],
        "system_prompt_1": "",
        "user_prompt_1": "",
        "llm_response_1": "",
        "system_prompt_2": "",
        "user_prompt_2": "",
        "llm_response_2": "",
        "system_prompt_3": "",
        "user_prompt_3": "",
        "llm_response_3": "",
        "not_selected_news": [],
        "original_news_data": [],
        "start_datetime": datetime.now(),
        "end_datetime": datetime.now() + timedelta(days=7)
    })
    
    # 전체 뉴스 목록 출력
    print_news(result["original_news_data"], "전체 뉴스 (50개)")
    
    # 분석 결과 출력
    print("\n\n=== 회계법인 관점의 분석 결과 ===")
    print(result["analysis"])
    
    # 선별된 뉴스 출력
    print_news(result["filtered_news"], "회계법인 관점의 주요 뉴스")

if __name__ == "__main__":
    main()
