#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Auto News Mailing Script
-----------------------
This script automatically processes news for selected companies and sends an email
with the results. It bypasses the Streamlit UI to work as a standalone script.
Supports GitHub Actions integration with PowerAutomate.
"""

import re
import os
import json
import sys
import requests
import urllib.parse
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from typing import List, Dict, Any, TypedDict, Optional

from googlenews import GoogleNews
from news_ai import (
    collect_news,
    filter_valid_press,
    filter_excluded_keywords,  # 새로운 키워드 필터링 함수 추가
    filter_excluded_news,
    group_and_select_news,
    evaluate_importance,
)
from automailing import send_email
from config import (
    DEFAULT_COMPANIES,
    COMPANY_KEYWORD_MAP,
    COMPANY_CATEGORIES,
    TRUSTED_PRESS_ALIASES,
    TRUSTED_PRESS_ALIASES_BY_CATEGORY,
    get_trusted_press_aliases_for_category,
    get_excluded_press_aliases_for_category,
    ADDITIONAL_PRESS_ALIASES,
    SYSTEM_PROMPT_1,
    SYSTEM_PROMPT_2,
    get_system_prompt_3,  # 함수로 변경 (이제 회사명 기반)
    SYSTEM_PROMPT_3_NO_LIMIT,  # 제한 없음 시스템 프롬프트
    get_max_articles_for_company,  # 회사별 최대 기사 수 유틸리티 함수
    MAX_ARTICLES_BY_COMPANY,  # 회사별 최대 기사 수
    MAX_ARTICLES_BY_CATEGORY,  # 하위 호환성용
    DEFAULT_MAX_ARTICLES,  # 기본 최대 기사 수
    NO_LIMIT,  # 제한 없음 상수
    EXCLUDED_KEYWORDS,  # Rule 기반 키워드 필터링 목록 (하위 호환성용)
    EXCLUDED_KEYWORDS_BY_CATEGORY, get_excluded_keywords_for_category, get_main_category_for_company,  # 카테고리별 키워드 필터링
    EXCLUSION_CRITERIA,
    get_exclusion_criteria_for_category,  # 카테고리별 제외 기준
    DUPLICATE_HANDLING,
    SELECTION_CRITERIA,
    DEFAULT_GPT_MODEL,
    EMAIL_SETTINGS,
    EMAIL_SETTINGS_BY_CATEGORY,
    SHAREPOINT_LIST_SETTINGS,
    # 회사별 특화 기준 추가
    COMPANY_ADDITIONAL_EXCLUSION_CRITERIA,
    COMPANY_ADDITIONAL_DUPLICATE_HANDLING,
    COMPANY_ADDITIONAL_SELECTION_CRITERIA,
    # 재평가용 완화 기준들
    RELAXED_EXCLUSION_CRITERIA,
    RELAXED_DUPLICATE_HANDLING,
    RELAXED_SELECTION_CRITERIA
)

# 한국 시간대(KST) 정의
KST = timezone(timedelta(hours=9))

# Define AgentState class for type hints
class AgentState(TypedDict, total=False):
    news_data: List[dict]
    filtered_news: List[dict]
    analysis: str
    keyword: str
    model: str
    excluded_news: List[dict]
    borderline_news: List[dict]
    retained_news: List[dict]
    grouped_news: List[dict]
    final_selection: List[dict]
    exclusion_criteria: str
    duplicate_handling: str
    selection_criteria: str
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
    valid_press_dict: Dict[str, List[str]]
    additional_press_dict: Dict[str, List[str]]
    start_datetime: datetime
    end_datetime: datetime
    is_reevaluated: bool

def clean_title(title):
    """Clean title by removing the press name pattern at the end and news tags at the beginning"""
    if not title:
        return ""
    
    # 0. 제목 앞의 특정 뉴스 태그 제거 (단독, 특징주, 속보만)
    title = re.sub(r'\[.*?\]', '', title).strip()  # 제목 안에 있는 모든 대괄호 제거 
    
    # 1. 특정 패턴 먼저 처리: "- 조선비즈 - Chosun Biz" (정확히 이 문자열만)
    title = re.sub(r'\s*-\s*조선비즈\s*-\s*Chosun Biz\s*$', '', title, flags=re.IGNORECASE)
    
    # 1-2. 특정 패턴 처리: "- 조선비즈 - Chosunbiz" (B가 소문자인 경우)
    title = re.sub(r'\s*-\s*조선비즈\s*-\s*Chosunbiz\s*$', '', title, flags=re.IGNORECASE)
    
    # 2. 특정 패턴 처리: "- fnnews.com"
    title = re.sub(r'\s*-\s*fnnews\.com\s*$', '', title, flags=re.IGNORECASE)
    
    # 3. 일반적인 언론사 패턴 처리 (기존 로직)
    title = re.sub(r"\s*-\s*[가-힣A-Za-z0-9\s]+$", "", title).strip()
    
    return title.strip()

def get_company_category(company):
    """
    회사명으로부터 해당하는 카테고리를 찾는 함수
    
    Args:
        company (str): 회사명
    
    Returns:
        str: 카테고리명 (Anchor, Growth_Whitespace, 시중은행, 지방은행 및 비은행 금융지주, 핀테크)
    """
    for main_category, sub_categories in COMPANY_CATEGORIES.items():
        for category, companies in sub_categories.items():
            if company in companies:
                return category
    return "Anchor"  # 기본값

def format_date(date_str):
    """Format date to MM/DD format with proper timezone handling"""
    try:
        # Try YYYY-MM-DD format
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        return date_obj.strftime('%m/%d')
    except Exception:
        try:
            # Try GMT format and convert to KST
            date_obj = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %Z')
            # Convert UTC to KST (add 9 hours)
            date_obj_kst = date_obj + timedelta(hours=9)
            return date_obj_kst.strftime('%m/%d')
        except Exception:
            try:
                # Try GMT format without timezone indicator
                date_obj = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S GMT')
                # Convert UTC to KST (add 9 hours)
                date_obj_kst = date_obj + timedelta(hours=9)
                return date_obj_kst.strftime('%m/%d')
            except Exception:
                # Return original if parsing fails
                return date_str if date_str else '날짜 정보 없음'

def create_html_email_with_sections(category_results, category_structure, category=None):
    """Create HTML email content with sections for new structure"""
    html_email_content = """
<div style="background:#f6f6f6; padding:40px 0; font-family:'맑은 고딕', Arial, sans-serif;">
  <div style="background: #fff; max-width: 700px; margin: auto; border-radius: 8px; box-shadow: 0 1px 6px rgba(0,0,0,0.06); padding: 36px 40px;">
    <div style="border-left: 6px solid #e03a3e; padding-left:16px; margin-bottom:24px;">
      <div style="font-size:22px; color:#e03a3e; font-weight:bold; letter-spacing:0.5px;">PwC Client Intelligence</div>
      <div style="font-size:15px; color:#555; margin-top:10px;">안녕하세요, 좋은 아침입니다.<br>오늘의 <b>Client Intelligence</b>를 전달 드립니다.</div>
    </div>
    
    <div style="border-bottom:2px solid #e03a3e; margin-bottom:18px; padding-bottom:4px; font-size:16px; font-weight:600; color:#333; letter-spacing:0.3px;">
      [Client Intelligence]
    </div>
"""
    # 각 섹션별 처리
    for section_name, companies in category_structure.items():
        # 섹션 제목 추가
        section_display_name = {
            "Anchor": "Anchor",
            "Growth_Whitespace": "Growth & Whitespace", 
            "금융지주": "금융지주",
            "비지주금융그룹": "비지주 금융그룹",
            "핀테크": "핀테크"
        }.get(section_name, section_name)
        
        html_email_content += f"""
    <!-- {section_display_name} 섹션 -->
    <div style="margin-top:24px; padding-top:16px; border-top:1px solid #ddd;">
      <div style="font-size:16px; font-weight:bold; color:#e03a3e; margin-bottom:12px; letter-spacing:0.3px;">
        [{section_display_name}]
      </div>
"""
        
        # 핀테크 섹션은 회사별 구분 없이 모든 기사를 하나의 목록으로 표출
        if section_name in ["핀테크"]:
            # 모든 회사의 기사들을 하나의 목록으로 수집 (중복 제거 포함)
            all_news_in_section = []
            seen_urls = set()
            seen_titles = set()
            
            for company in companies:
                news_list = category_results.get(company, [])
                for news in news_list:
                    url = news.get('url', '')
                    title = clean_title(news.get('title', ''))
                    
                    # URL 기반 중복 체크 (가장 확실한 방법)
                    if url and url in seen_urls:
                        print(f"[핀테크 중복 제거] URL 중복: {title}")
                        continue
                    
                    # 제목 기반 중복 체크 (URL이 없거나 다른 경우)
                    if title and title in seen_titles:
                        print(f"[핀테크 중복 제거] 제목 중복: {title}")
                        continue
                    
                    # 중복이 아닌 경우 추가
                    all_news_in_section.append(news)
                    if url:
                        seen_urls.add(url)
                    if title:
                        seen_titles.add(title)
            
            html_email_content += """
      <ul style="list-style-type:none; padding-left:0; margin:0;">"""
            
            if not all_news_in_section:
                # No news selected for this section
                html_email_content += """
        <li style="margin-bottom:9px; font-size:14px; color:#888;">
          AI 분석결과 금일자로 회계법인 관점에서 특별히 주목할 만한 기사가 없습니다.
        </li>"""
            else:
                for news in all_news_in_section:
                    date_str = format_date(news.get('date', ''))
                    url = news.get('url', '')
                    title = clean_title(news.get('title', ''))
                    
                    # Add news item
                    html_email_content += f"""
        <li style="margin-bottom:9px; font-size:14px;">
          <span style="font-weight:bold; color:#333;">- {title} ({date_str})</span>
          <a href="{url}" style="color:#e03a3e; text-decoration:underline;">[기사 보기]</a>
        </li>"""
            
            html_email_content += """
      </ul>"""
        
        else:
            # 기존 방식: 회사별 구분하여 표출 (Anchor, Growth_Whitespace, 시중은행)
            company_counter = 1
            for company in companies:
                # 새마을금고등의 경우 특별 처리 (제목 자체를 변경하고 회색으로 표시, 넘버링 없음)
                if company == "새마을금고등":
                    company_display_name = "[ 상호금융 및 IBK ]"
                    html_email_content += f"""
      <div style="margin-top:18px;">
        <div style="font-size:12px; color:#666; margin-bottom:6px; margin-top:2px;">
          {company_display_name}
        </div>"""
                else:
                    company_display_name = company
                    html_email_content += f"""
      <div style="margin-top:18px;">
        <div style="font-size:15px; font-weight:bold; color:#004578; margin-bottom:6px; margin-top:20px;">
          {company_counter}. {company_display_name}
        </div>"""
                    
        #             # 지방은행 및 비은행 금융지주의 경우 제목 아래에 설명 추가
        #             if company == "지방은행 및 비은행 금융지주":
        #                 html_email_content += """
        # <div style="font-size:12px; color:#666; margin-bottom:6px; margin-top:2px;">
        #   *IM금융 포함
        # </div>"""
                
                html_email_content += """
        <ul style="list-style-type:none; padding-left:0; margin:0;">"""
                
                # Get news for this company
                news_list = category_results.get(company, [])
                
                if not news_list:
                    # No news selected for this company
                    html_email_content += """
          <li style="margin-bottom:9px; font-size:14px; color:#888;">
            AI 분석결과 금일자로 회계법인 관점에서 특별히 주목할 만한 기사가 없습니다.
          </li>"""
                else:
                    for news in news_list:
                        date_str = format_date(news.get('date', ''))
                        url = news.get('url', '')
                        title = clean_title(news.get('title', ''))
                        
                        # Add news item
                        html_email_content += f"""
          <li style="margin-bottom:9px; font-size:14px;">
            <span style="font-weight:bold; color:#333;">- {title} ({date_str})</span>
            <a href="{url}" style="color:#e03a3e; text-decoration:underline;">[기사 보기]</a>
          </li>"""
                
                html_email_content += """
        </ul>
      </div>"""
                
                # 새마을금고등은 넘버링에서 제외하므로 카운터 증가하지 않음
                if company != "새마을금고등":
                    company_counter += 1
        
        html_email_content += """
    </div>"""
    
    # Corporate 카테고리인 경우 금융GSP 안내 문구 추가
    gsp_notice = ""
    if category and category.lower() == "corporate":
        gsp_notice = "※ 금융GSP는 별도의 '금융Client intelligence'로 뉴스클리핑이 제공될 예정입니다.<br>"

    # Add footer
    html_email_content += f"""
    <!-- 맺음말 -->
    <div style="margin-top:32px; padding-top:16px; border-top:1px solid #eee; font-size:14px; color:#666;">
      감사합니다.<br>
      <span style="font-weight:bold; color:#e03a3e;">Clients &amp; Industries 드림</span><br>
      <span style="display:block; margin-top:12px; font-size:13px; color:#888;">
        {gsp_notice}※ 본 Client intelligence는 AI를 통해 주요 뉴스만 수집한 내용입니다. 일부 정확하지 못한 내용이 있는 경우, Market으로 말씀주시면 수정하도록 하겠습니다.
      </span>
    </div>
    
    <!-- PwC 로고 -->
    <div style="margin-top:32px; text-align:right;">
      <div style="font-size:12px; color:#e03a3e; font-weight:bold;">PwC</div>
    </div>
  </div>
</div>"""
    
    return html_email_content

def create_html_email(all_results, selected_companies):
    """Create HTML email content from results (deprecated - use create_html_email_with_sections)"""
    html_email_content = """
<div style="background:#f6f6f6; padding:40px 0; font-family:'맑은 고딕', Arial, sans-serif;">
  <div style="background: #fff; max-width: 700px; margin: auto; border-radius: 8px; box-shadow: 0 1px 6px rgba(0,0,0,0.06); padding: 36px 40px;">
    <div style="border-left: 6px solid #e03a3e; padding-left:16px; margin-bottom:24px;">
      <div style="font-size:22px; color:#e03a3e; font-weight:bold; letter-spacing:0.5px;">PwC Client Intelligence</div>
      <div style="font-size:15px; color:#555; margin-top:10px;">안녕하세요, 좋은 아침입니다.<br>오늘의 <b>Client Intelligence</b>를 전달 드립니다.</div>
    </div>
    
    <div style="border-bottom:2px solid #e03a3e; margin-bottom:18px; padding-bottom:4px; font-size:16px; font-weight:600; color:#333; letter-spacing:0.3px;">
      [Client Intelligence]
    </div>
"""
    
    # Add company sections
    for i, company in enumerate(selected_companies, 1):
        html_email_content += f"""
    <div style="margin-top:18px;">
      <div style="font-size:15px; font-weight:bold; color:#004578; margin-bottom:6px; margin-top:20px;">
        {i}. {company}
      </div>
      <ul style="list-style-type:none; padding-left:0; margin:0;">"""
        
        # Get news for this company
        news_list = all_results.get(company, [])
        
        if not news_list:
            # No news selected for this company
            html_email_content += """
        <li style="margin-bottom:9px; font-size:14px; color:#888;">
          AI 분석결과 금일자로 회계법인 관점에서 특별히 주목할 만한 기사가 없습니다.
        </li>"""
        else:
            for news in news_list:
                date_str = format_date(news.get('date', ''))
                url = news.get('url', '')
                title = clean_title(news.get('title', ''))
                
                # Add news item
                html_email_content += f"""
        <li style="margin-bottom:9px; font-size:14px;">
          <span style="font-weight:bold; color:#333;">- {title} ({date_str})</span>
          <a href="{url}" style="color:#e03a3e; text-decoration:underline;">[기사 보기]</a>
        </li>"""
        
        html_email_content += """
      </ul>
    </div>"""
    
    # Add footer
    html_email_content += """
    <!-- 맺음말 -->
    <div style="margin-top:32px; padding-top:16px; border-top:1px solid #eee; font-size:14px; color:#666;">
      감사합니다.<br>
      <span style="font-weight:bold; color:#e03a3e;">Clients &amp; Industries 드림</span><br>
      <span style="display:block; margin-top:12px; font-size:13px; color:#888;">
        ※ 본 Client intelligence는 AI를 통해 주요 뉴스만 수집한 내용입니다. 일부 정확하지 못한 내용이 있는 경우, Market으로 말씀주시면 수정하도록 하겠습니다.
      </span>
    </div>
    
    <!-- PwC 로고 -->
    <div style="margin-top:32px; text-align:right;">
      <div style="font-size:12px; color:#e03a3e; font-weight:bold;">PwC</div>
    </div>
  </div>
</div>"""
    
    return html_email_content

def process_company_news(company, keywords):
    """Process news for a specific company"""
    print(f"\n===== 분석 시작: {company} =====")
    
    # Calculate default date ranges - 한국 시간 기준
    now = datetime.now(KST)
    #now = datetime(2025, 5, 29, 8, 0, 0, 0, tzinfo=timezone(timedelta(seconds=32400)))

    
    # 현재 시간과 시간대 정보 출력
    print(f"현재 시각 (KST): {now}")
    print(f"현재 날짜: {now.date()}")
    print(f"현재 시간: {now.time()}")
    print(f"시간대: {now.tzinfo}")
    
    # 회사별 카테고리 판단 (날짜 범위 설정 전에 필요)
    print(f"\n=== 회사별 카테고리 판단 ===")
    company_category = get_company_category(company)
    main_category = get_main_category_for_company(company)
    print(f"[{company}] 카테고리: {company_category} (메인: {main_category})")
    
    # 날짜 범위 설정 - Financial 카테고리 월요일 특별 처리
    if main_category == "Financial" and now.weekday() == 0:  # 월요일 (0=월요일)
        # Financial 카테고리 월요일: 토요일부터 검색 (토, 일, 월)
        default_start_date = now - timedelta(days=3)  # 3일 전 (금요일)
        print(f"📅 Financial 카테고리 월요일 특별 처리: 토요일부터 검색")
    else:
        # 기본: 어제부터 검색
        default_start_date = now - timedelta(days=1)
    
    # Set time to 8:00 AM for both start and end - 한국 시간 기준
    start_datetime = datetime.combine(default_start_date.date(), 
                                     datetime.strptime("08:00", "%H:%M").time(), KST)
    end_datetime = datetime.combine(now.date(), 
                                   datetime.strptime("08:00", "%H:%M").time(), KST)
    
    # 날짜 범위 상세 출력
    print(f"\n=== 날짜 범위 설정 ===")
    if main_category == "Financial" and now.weekday() == 0:
        print(f"시작 날짜시간: {start_datetime} (금금요일 8시 - Financial 월요일 특별 처리)")
    else:
        print(f"시작 날짜시간: {start_datetime} (어제 8시)")
    print(f"종료 날짜시간: {end_datetime} (오늘 8시)")
    print(f"검색 범위: {start_datetime.strftime('%Y-%m-%d %H:%M')} ~ {end_datetime.strftime('%Y-%m-%d %H:%M')}")
    
    # 회사별 특화 기준 적용
    print(f"\n=== 회사별 특화 기준 적용 ===")
    
    # 1. 카테고리별 키워드 필터링 설정
    excluded_keywords = get_excluded_keywords_for_category(main_category)
    if excluded_keywords:
        print(f"[{company}] Rule 기반 키워드 필터링 적용: {len(excluded_keywords)}개 키워드")
        print(f"[{company}] 제외 키워드: {excluded_keywords}")
    else:
        print(f"[{company}] Rule 기반 키워드 필터링 비활성화 ({main_category} 카테고리)")
    
    # 2. 회사별 최대 기사 수 확인 (우선적으로 회사별 설정 사용)
    max_articles = get_max_articles_for_company(company)
    if max_articles == NO_LIMIT:
        print(f"[{company}] 최대 기사 수: 제한 없음 (중요도에 따라 모든 기사 선정 가능)")
    else:
        print(f"[{company}] 최대 기사 수: {max_articles}개")
    
    # 3. 회사별 시스템 프롬프트 생성
    dynamic_system_prompt_3 = get_system_prompt_3(company)
    
    # 4. 회사별 특화 기준 적용 (카테고리별 제외 기준 사용)
    base_exclusion = get_exclusion_criteria_for_category(main_category)
    base_duplicate = DUPLICATE_HANDLING
    base_selection = SELECTION_CRITERIA
    
    # 5. 카테고리별 언론사 설정 적용
    category_press_aliases = get_trusted_press_aliases_for_category(main_category)
    print(f"[{company}] 카테고리별 언론사 설정 적용: {len(category_press_aliases)}개 언론사")
    
    # 5-1. 카테고리별 제외 언론사 설정 적용
    excluded_press_aliases = get_excluded_press_aliases_for_category(main_category)
    if excluded_press_aliases:
        print(f"[{company}] 카테고리별 제외 언론사 적용: {len(excluded_press_aliases)}개 언론사")
    
    # 회사별 키워드 정보를 동적으로 추가
    company_keywords = COMPANY_KEYWORD_MAP.get(company, [company])
    company_keywords_info = f"\n\n[분석 대상 기업별 키워드 목록]\n• {company}: {', '.join(company_keywords)}\n"
    
    # 키워드 연관성 체크 기준을 동적으로 업데이트
    updated_base_exclusion = base_exclusion.replace(
        "• 각 회사별 키워드 목록은 COMPANY_KEYWORD_MAP 참조",
        f"- 해당 기업의 키워드: {company_keywords_info.strip()}"
    )
    updated_base_selection = base_selection.replace(
        "• 각 회사별 키워드 목록은 COMPANY_KEYWORD_MAP 참조",
        f"- 해당 기업의 키워드: {company_keywords_info.strip()}"
    )
    # 해당 회사의 추가 특화 기준 가져오기
    company_additional_exclusion = COMPANY_ADDITIONAL_EXCLUSION_CRITERIA.get(company, "")
    company_additional_duplicate = COMPANY_ADDITIONAL_DUPLICATE_HANDLING.get(company, "")
    company_additional_selection = COMPANY_ADDITIONAL_SELECTION_CRITERIA.get(company, "")
    
    # 기본 기준 + 회사별 특화 기준 결합
    enhanced_exclusion_criteria = updated_base_exclusion + company_additional_exclusion
    enhanced_duplicate_handling = base_duplicate + company_additional_duplicate  
    enhanced_selection_criteria = updated_base_selection + company_additional_selection
    
    # 특화 기준 적용 여부 로깅
    if company_additional_exclusion:
        print(f"[{company}] 제외 특화 기준 적용됨")
    if company_additional_duplicate:
        print(f"[{company}] 그룹핑 특화 기준 적용됨")
    if company_additional_selection:
        print(f"[{company}] 선택 특화 기준 적용됨")
    
    # Initial state setup
    initial_state = {
        "news_data": [], 
        "filtered_news": [], 
        "analysis": "", 
        "keyword": keywords,
        "model": DEFAULT_GPT_MODEL,
        "excluded_news": [],
        "borderline_news": [],
        "retained_news": [],
        "grouped_news": [],
        "final_selection": [],
        # 회사별 enhanced 기준들 적용 🎯
        "exclusion_criteria": enhanced_exclusion_criteria,
        "duplicate_handling": enhanced_duplicate_handling,
        "selection_criteria": enhanced_selection_criteria,
        "system_prompt_1": SYSTEM_PROMPT_1,
        "user_prompt_1": "",
        "llm_response_1": "",
        "system_prompt_2": SYSTEM_PROMPT_2,
        "user_prompt_2": "",
        "llm_response_2": "",
        "system_prompt_3": dynamic_system_prompt_3,
        "user_prompt_3": "",
        "llm_response_3": "",
        "not_selected_news": [],
        "original_news_data": [],
        "valid_press_dict": category_press_aliases,  # 카테고리별 언론사 설정 사용
        "additional_press_dict": ADDITIONAL_PRESS_ALIASES,
        "excluded_press_aliases": excluded_press_aliases,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "excluded_keywords": excluded_keywords # 카테고리별 키워드 적용
    }
    
    # Process news through pipeline
    print("1단계: 뉴스 수집 중...")
    state_after_collection = collect_news(initial_state)
    
    print("2단계: 유효 언론사 필터링 중...")
    state_after_press_filter = filter_valid_press(state_after_collection)
    
    print("2.5단계: Rule 기반 키워드 필터링 중...")
    state_after_keyword_filter = filter_excluded_keywords(state_after_press_filter)
    
    print("3단계: 제외 판단 중...")
    state_after_exclusion = filter_excluded_news(state_after_keyword_filter)
    
    print("4단계: 그룹핑 중...")
    state_after_grouping = group_and_select_news(state_after_exclusion)
    
    print("5단계: 중요도 평가 중...")
    final_state = evaluate_importance(state_after_grouping)

    # 6단계: 0개 선택 시 완화된 기준으로 처음부터 재평가
    if len(final_state["final_selection"]) == 0:
        # Financial 카테고리는 재평가를 수행하지 않음
        if company_category == "금융지주" or company_category == "비지주금융그룹" or company_category == "핀테크":
            print(f"6단계: [{company}] Financial 카테고리는 재평가를 수행하지 않습니다. (카테고리: {company_category})")
        else:
            print("6단계: 선택된 뉴스가 없어 완화된 기준으로 처음부터 재평가를 시작합니다...")
            
            # 추가 언론사를 포함한 확장된 언론사 설정 (카테고리별 언론사 + 추가 언론사)
            expanded_valid_press_dict = {**category_press_aliases, **ADDITIONAL_PRESS_ALIASES}
            
            # 회사별 키워드 정보를 완화된 기준에도 동적으로 추가
            # 카테고리에 따라 다른 완화된 기준 사용 (Financial의 경우 일반 인사/내부 운영 제외)
            category_relaxed_exclusion = RELAXED_EXCLUSION_CRITERIA  # 기본 완화 기준 사용 (모든 카테고리 동일)
            updated_relaxed_exclusion = category_relaxed_exclusion.replace(
                "- 각 회사별 키워드 목록은 COMPANY_KEYWORD_MAP 참조",
                f"- 해당 기업의 키워드: {company_keywords_info.strip()}"
            )
            
            # selection_criteria에도 키워드 정보 반영
            updated_relaxed_selection = RELAXED_SELECTION_CRITERIA.replace(
                "• 각 회사별 키워드 목록은 COMPANY_KEYWORD_MAP 참조",
                f" - 해당 기업의 키워드: {company_keywords_info.strip()}"
            )
            
            # 회사별 완화된 특화 기준 생성
            relaxed_exclusion_criteria = updated_relaxed_exclusion + company_additional_exclusion
            relaxed_duplicate_handling = RELAXED_DUPLICATE_HANDLING + company_additional_duplicate
            relaxed_selection_criteria = updated_relaxed_selection + company_additional_selection
            
            # 완화된 기준으로 새로운 초기 상태 생성 (기존 수집된 뉴스 재사용)
            relaxed_initial_state = {
                "news_data": final_state.get("original_news_data", []),  # 기존 수집된 뉴스를 news_data로 복사
                "filtered_news": [], 
                "analysis": "", 
                "keyword": keywords,
                "model": DEFAULT_GPT_MODEL,
                "excluded_news": [],
                "borderline_news": [],
                "retained_news": [],
                "grouped_news": [],
                "final_selection": [],
                # 완화된 기준들 적용
                "exclusion_criteria": relaxed_exclusion_criteria,
                "duplicate_handling": relaxed_duplicate_handling,
                "selection_criteria": relaxed_selection_criteria,
                "system_prompt_1": SYSTEM_PROMPT_1,
                "user_prompt_1": "",
                "llm_response_1": "",
                "system_prompt_2": SYSTEM_PROMPT_2,
                "user_prompt_2": "",
                "llm_response_2": "",
                "system_prompt_3": dynamic_system_prompt_3,
                "user_prompt_3": "",
                "llm_response_3": "",
                "not_selected_news": [],
                # 기존 수집된 뉴스 데이터 재사용
                "original_news_data": final_state.get("original_news_data", []),
                # 확장된 언론사 설정 적용 (추가 언론사 포함)
                "valid_press_dict": expanded_valid_press_dict,
                # 추가 언론사는 빈 딕셔너리로 (이미 valid_press_dict에 포함됨)
                "additional_press_dict": {},
                # 날짜 필터 정보
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "excluded_keywords": excluded_keywords # 카테고리별 키워드 적용
            }
            
            print("- 1단계: 기존 수집된 뉴스 재사용 (재평가)")
            # 뉴스 수집 단계 건너뛰고 기존 데이터 사용
            relaxed_state_after_collection = relaxed_initial_state
            
            print("- 2단계: 확장된 언론사 필터링 (재평가) 중...")
            relaxed_state_after_press_filter = filter_valid_press(relaxed_state_after_collection)
            
            print("- 2.5단계: Rule 기반 키워드 필터링 (재평가) 중...")
            relaxed_state_after_keyword_filter = filter_excluded_keywords(relaxed_state_after_press_filter)
            
            print("- 3단계: 완화된 제외 판단 (재평가) 중...")
            relaxed_state_after_exclusion = filter_excluded_news(relaxed_state_after_keyword_filter)
            
            print("- 4단계: 완화된 그룹핑 (재평가) 중...")
            relaxed_state_after_grouping = group_and_select_news(relaxed_state_after_exclusion)
            
            print("- 5단계: 완화된 중요도 평가 (재평가) 중...")
            relaxed_final_state = evaluate_importance(relaxed_state_after_grouping)
            
            # 재평가 결과가 있으면 최종 상태 업데이트
            if "final_selection" in relaxed_final_state and relaxed_final_state["final_selection"]:
                final_state.update(relaxed_final_state)
                final_state["is_reevaluated"] = True
                print(f"완화된 기준으로 재평가 후 {len(final_state['final_selection'])}개의 뉴스가 선택되었습니다.")
            else:
                print("완화된 기준으로 재평가 후에도 선정할 수 있는 뉴스가 없습니다.")
    
    print(f"===== 분석 완료: {company} =====")
    print(f"선정된 뉴스: {len(final_state['final_selection'])}개")
    
    return final_state["final_selection"]

# 현재 날짜를 가져오는 함수 추가
def get_current_date_str():
    """현재 날짜를 YYYY-MM-DD 형식으로 반환합니다. (한국 시간 기준)"""
    return datetime.now(KST).strftime('%Y-%m-%d')

# PowerAutomate webhook 전송 함수 추가
def send_to_powerautomate(data, webhook_url=None):
    """PowerAutomate webhook으로 데이터를 전송합니다."""
    if not webhook_url:
        webhook_url = os.environ.get('POWERAUTOMATE_WEBHOOK_URL')
    
    if not webhook_url:
        print("PowerAutomate webhook URL이 설정되지 않았습니다.")
        return False, None
    
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(webhook_url, json=data, headers=headers, timeout=30)
        
        print(f"PowerAutomate 응답 상태 코드: {response.status_code}")
        if response.status_code == 200:
            print("PowerAutomate로 데이터 전송 성공")
            return True, response
        else:
            print(f"PowerAutomate 전송 실패: {response.text}")
            return False, response
            
    except Exception as e:
        print(f"PowerAutomate 전송 중 오류: {str(e)}")
        return False, None

# SharePoint List에 뉴스 저장 함수 (일반 모드 전용)
def send_to_sharepoint_list(news_items, webhook_url=None):
    """SharePoint List에 뉴스 아이템들을 저장합니다. (일반 모드에서만 사용)"""
    if not webhook_url:
        webhook_url = os.environ.get('POWERAUTOMATE_SHAREPOINT_WEBHOOK_URL', os.environ.get('POWERAUTOMATE_WEBHOOK_URL'))
    
    if not webhook_url:
        print("PowerAutomate SharePoint webhook URL이 설정되지 않았습니다.")
        return False, None
    
    # SharePoint List 데이터 구성
    sharepoint_data = {
        "action": "sharepoint_list_add",
        "items": news_items
    }
    
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(webhook_url, json=sharepoint_data, headers=headers, timeout=30)
        
        print(f"SharePoint List 저장 응답 상태 코드: {response.status_code}")
        if response.status_code == 200:
            print("SharePoint List 저장 성공")
            return True, response
        else:
            print(f"SharePoint List 저장 실패: {response.text}")
            return False, response
            
    except Exception as e:
        print(f"SharePoint List 저장 중 오류: {str(e)}")
        return False, None

def shorten_url_with_service(url):
    """URL 단축 서비스를 사용하여 URL을 단축합니다. (선택적)"""
    try:
        # TinyURL API 사용 (무료, API 키 불필요)
        import requests
        response = requests.get(f"http://tinyurl.com/api-create.php?url={urllib.parse.quote(url)}", timeout=5)
        if response.status_code == 200 and response.text.startswith('http'):
            return response.text.strip()
    except Exception as e:
        print(f"URL 단축 서비스 오류: {str(e)}")
    
    return None

def truncate_url_for_sharepoint(url, max_length=255, use_shortener=True):
    """SharePoint Hyperlink 컬럼의 255자 제한에 맞게 URL을 처리합니다. 기본적으로 TinyURL을 사용합니다."""
    if not url or len(url) <= max_length:
        return url
    
    # URL 단축 서비스 사용 (기본값: True)
    if use_shortener:
        shortened = shorten_url_with_service(url)
        if shortened and len(shortened) <= max_length:
            print(f"URL 단축 성공: {len(url)}자 -> {len(shortened)}자")
            return shortened
        else:
            print(f"URL 단축 실패 또는 여전히 길이 초과. 원본 URL 처리를 시도합니다.")
    
    try:
        # Google News URL의 경우 중요한 부분만 유지
        if 'news.google.com' in url:
            # Google News URL 구조: https://news.google.com/articles/...?hl=ko&gl=KR&ceid=KR%3Ako
            # 기본 부분만 유지하고 파라미터는 최소화
            base_url = url.split('?')[0]  # 파라미터 제거
            if len(base_url) <= max_length:
                return base_url
            else:
                # 그래도 길면 articles ID 부분만 유지
                if '/articles/' in base_url:
                    article_part = base_url.split('/articles/')[1]
                    # 첫 번째 하이픈까지만 유지 (보통 기사 ID)
                    article_id = article_part.split('-')[0] if '-' in article_part else article_part[:50]
                    return f"https://news.google.com/articles/{article_id}"
        
        # 일반 URL의 경우 도메인 + 경로 일부만 유지
        from urllib.parse import urlparse
        parsed = urlparse(url)
        
        # 기본 구조: scheme + netloc + path 일부
        base_length = len(f"{parsed.scheme}://{parsed.netloc}")
        remaining_length = max_length - base_length - 10  # 여유분 10자
        
        if remaining_length > 0 and parsed.path:
            # 경로를 적절히 자르기
            path_parts = parsed.path.split('/')
            truncated_path = ""
            for part in path_parts:
                if len(truncated_path + "/" + part) <= remaining_length:
                    truncated_path += "/" + part
                else:
                    break
            
            return f"{parsed.scheme}://{parsed.netloc}{truncated_path}"
        else:
            return f"{parsed.scheme}://{parsed.netloc}"
            
    except Exception as e:
        print(f"URL 자르기 중 오류: {str(e)}")
        # 오류 발생 시 단순히 앞에서부터 자르기
        return url[:max_length-3] + "..."

# 회사별 SharePoint List 아이템 생성 함수
def create_sharepoint_list_items(company, news_list, current_date, sharepoint_config):
    """회사별 SharePoint List 아이템들을 생성합니다."""
    items = []
    
    # 현재 날짜에서 월 추출
    try:
        date_obj = datetime.strptime(current_date, '%Y-%m-%d')
        month = f"{date_obj.month}월"  # 1월, 2월 형식
    except:
        month = current_date[:7] if len(current_date) >= 7 else current_date
    
    # 뉴스가 있는 경우에만 아이템 생성
    if news_list:
        for news in news_list:
            url = news.get('url', '')
            title = clean_title(news.get('title', ''))
            
            # SharePoint Hyperlink 컬럼 제한에 맞게 URL 처리 (TinyURL 기본 사용)
            truncated_url = truncate_url_for_sharepoint(url)
            
            # URL 처리 결과 로깅
            if len(url) > 255:
                print(f"[{company}] URL 처리: {len(url)}자 -> {len(truncated_url)}자")
                if len(truncated_url) > 255:
                    print(f"[{company}] 경고: 처리된 URL이 여전히 255자를 초과합니다: {len(truncated_url)}자")
            
            # SharePoint List 아이템 생성 (PowerAutomate 형식에 맞춤)
            items.append({
                "company": company,
                "site_url": sharepoint_config.get("site_url", ""),
                "list_id": sharepoint_config.get("list_id", ""),
                "column_ids": sharepoint_config.get("column_ids", {}),
                "data": {
                    "Month": month,
                    "날짜": current_date,
                    "제목": title,
                    "링크": truncated_url
                }
            })
    
    return items

# 카테고리별 SharePoint List 처리 함수 (일반 모드 전용)
def process_sharepoint_list_by_category(category, category_results):
    """카테고리별로 SharePoint List에 뉴스를 저장합니다. (일반 모드에서만 사용)"""
    current_date = get_current_date_str()
    
    # PowerAutomate에서 전달된 SharePoint 설정 확인
    powerautomate_sharepoint_settings = None
    pa_sharepoint_json = os.environ.get('POWERAUTOMATE_SHAREPOINT_SETTINGS')
    if pa_sharepoint_json:
        try:
            pa_sharepoint = json.loads(pa_sharepoint_json)
            # 현재 카테고리의 설정이 있는지 확인
            if category in pa_sharepoint:
                powerautomate_sharepoint_settings = pa_sharepoint[category]
                print(f"[{category}] PowerAutomate에서 전달된 SharePoint 설정을 사용합니다.")
        except json.JSONDecodeError:
            print(f"[{category}] PowerAutomate SharePoint 설정 파싱 실패. 기본 설정을 사용합니다.")
    
    # SharePoint 설정 가져오기 (PowerAutomate 우선, 없으면 config.py)
    if powerautomate_sharepoint_settings:
        sharepoint_settings = powerautomate_sharepoint_settings
    else:
        sharepoint_settings = SHAREPOINT_LIST_SETTINGS.get(category)
        
    if not sharepoint_settings or not sharepoint_settings.get("enabled", False):
        print(f"[{category}] SharePoint List 설정이 없거나 비활성화되어 있습니다.")
        return False
    
    all_items = []
    companies_config = sharepoint_settings.get("companies", {})
    
    # 각 회사별로 SharePoint List 아이템 생성
    for company, news_list in category_results.items():
        # 회사별 SharePoint 설정 가져오기
        company_config = companies_config.get(company)
        if not company_config:
            print(f"[{category}] {company} SharePoint 설정이 없습니다.")
            continue
            
        # SharePoint List 아이템들 생성
        items = create_sharepoint_list_items(company, news_list, current_date, company_config)
        all_items.extend(items)
        
        if items:
            print(f"[{category}] {company} SharePoint List 아이템 {len(items)}개 생성")
    
    # 모든 아이템을 한 번에 전송
    if all_items:
        print(f"[{category}] 총 {len(all_items)}개 아이템을 SharePoint List에 저장 중...")
        success, response = send_to_sharepoint_list(all_items)
        
        if success:
            print(f"[{category}] SharePoint List 저장 성공")
        else:
            print(f"[{category}] SharePoint List 저장 실패")
        
        return success
    else:
        print(f"[{category}] 저장할 아이템이 없습니다.")
        return False

# 카테고리별 GitHub Actions 결과 출력 함수
def output_github_actions_result_by_category(category, all_results, category_structure, mode="email"):
    """카테고리별 GitHub Actions 실행 결과를 출력합니다 (새로운 섹션 구조)"""
    current_date = get_current_date_str()
    
    # 이메일 모드인 경우에만 PowerAutomate로 전송
    if mode == "email":
        # 새로운 HTML 생성 함수 사용
        html_content = create_html_email_with_sections(all_results, category_structure, category)
        
        # PowerAutomate에서 전달된 이메일 설정 확인
        powerautomate_email_settings = None
        pa_settings_json = os.environ.get('POWERAUTOMATE_EMAIL_SETTINGS')
        if pa_settings_json:
            try:
                pa_settings = json.loads(pa_settings_json)
                # 현재 카테고리의 설정이 있는지 확인
                if category in pa_settings:
                    powerautomate_email_settings = pa_settings[category]
                    print(f"[{category}] PowerAutomate에서 전달된 이메일 설정을 사용합니다.")
            except json.JSONDecodeError:
                print(f"[{category}] PowerAutomate 이메일 설정 파싱 실패. 기본 설정을 사용합니다.")
        
        # PowerAutomate에서 전달된 SharePoint 설정 확인
        powerautomate_sharepoint_settings = None
        pa_sharepoint_json = os.environ.get('POWERAUTOMATE_SHAREPOINT_SETTINGS')
        if pa_sharepoint_json:
            try:
                pa_sharepoint = json.loads(pa_sharepoint_json)
                # 현재 카테고리의 설정이 있는지 확인
                if category in pa_sharepoint:
                    powerautomate_sharepoint_settings = pa_sharepoint[category]
                    print(f"[{category}] PowerAutomate에서 전달된 SharePoint 설정을 사용합니다.")
            except json.JSONDecodeError:
                print(f"[{category}] PowerAutomate SharePoint 설정 파싱 실패. 기본 설정을 사용합니다.")
        
        # PowerAutomate 설정이 있으면 사용, 없으면 config.py의 설정 사용
        if powerautomate_email_settings:
            email_to = powerautomate_email_settings.get("to", EMAIL_SETTINGS_BY_CATEGORY[category]["to"])
            email_cc = powerautomate_email_settings.get("cc", EMAIL_SETTINGS_BY_CATEGORY[category]["cc"])
            email_bcc = powerautomate_email_settings.get("bcc", EMAIL_SETTINGS_BY_CATEGORY[category].get("bcc", ""))
            email_from = powerautomate_email_settings.get("from", EMAIL_SETTINGS["from"])
            # subject는 한국 시간 기준으로 설정
            if category == "Corporate":
                category_display_name = "GSP"
            elif category == "Financial":
                category_display_name = "금융GSP 및 주요 금융기업"
            else:
                category_display_name = category
            subject_prefix = f"({datetime.now(KST).strftime('%m%d')}) Client Intelligence - {category_display_name}"
        else:
            # 기존 config.py 설정 사용
            category_email_settings = EMAIL_SETTINGS_BY_CATEGORY.get(category, EMAIL_SETTINGS_BY_CATEGORY["Corporate"])
            email_to = category_email_settings["to"]
            email_cc = category_email_settings["cc"]
            email_bcc = category_email_settings.get("bcc", "")
            email_from = EMAIL_SETTINGS["from"]
            # subject는 한국 시간 기준으로 설정
            if category == "Corporate":
                category_display_name = "GSP"
            elif category == "Financial":
                category_display_name = "금융GSP 및 주요 금융기업"
            else:
                category_display_name = category
            subject_prefix = f"({datetime.now(KST).strftime('%m%d')}) Client Intelligence - {category_display_name}"
        
        # SharePoint 아이템들 생성
        sharepoint_items = []
        
        # SharePoint 설정 가져오기 (PowerAutomate 우선, 없으면 config.py)
        if powerautomate_sharepoint_settings:
            sharepoint_settings = powerautomate_sharepoint_settings
        else:
            sharepoint_settings = SHAREPOINT_LIST_SETTINGS.get(category)
            
        if sharepoint_settings and sharepoint_settings.get("enabled", False):
            companies_config = sharepoint_settings.get("companies", {})
            
            # 각 회사별로 SharePoint List 아이템 생성
            for company, news_list in all_results.items():
                # 회사별 SharePoint 설정 가져오기
                company_config = companies_config.get(company)
                if not company_config:
                    print(f"[{category}] {company} SharePoint 설정이 없습니다.")
                    continue
                    
                # SharePoint List 아이템들 생성
                items = create_sharepoint_list_items(company, news_list, current_date, company_config)
                sharepoint_items.extend(items)
                
                if items:
                    print(f"[{category}] {company} SharePoint List 아이템 {len(items)}개 생성")
        
        # 통합 데이터 구성 (이메일 + SharePoint)
        unified_data = {
            # 이메일 데이터
            "to": email_to,
            "cc": email_cc,
            "from": email_from,
            "bcc": email_bcc,
            "subject": subject_prefix,
            "body": html_content,
            "importance": EMAIL_SETTINGS["importance"],
            
            # SharePoint 아이템들 (PowerAutomate 플로우에서 처리)
            "sharepoint_items": sharepoint_items
        }
        
        # 전체 회사 목록 생성 (평면화)
        all_companies = []
        for companies in category_structure.values():
            all_companies.extend(companies)
        
        print(f"[{category}] 통합 데이터가 생성되었습니다. PowerAutomate에서 이메일과 SharePoint를 처리합니다.")
        print(f"[{category}] 수신자: {email_to}, 참조: {email_cc}, 숨은참조: {email_bcc}")
        print(f"[{category}] SharePoint 아이템 수: {len(sharepoint_items)}개")
        
        # PowerAutomate로 통합 데이터 전송
        webhook_success, webhook_response = send_to_powerautomate(unified_data)
        
        # 결과 요약 생성 (로깅용)
        summary = {
            "execution_date": current_date,
            "execution_time": datetime.now().isoformat(),
            "category": category,
            "mode": mode,
            "companies_processed": len(all_companies),
            "companies": all_companies,
            "total_news_selected": sum(len(news_list) for news_list in all_results.values()),
            "sharepoint_items_count": len(sharepoint_items),
            "webhook_sent": webhook_success,
            "email_sent_to": email_to,
            "email_cc": email_cc,
            "email_bcc": email_bcc
        }
        
        # GitHub Actions 출력 (로깅용)
        print(f"::set-output name={category.lower()}_summary::{json.dumps(summary, ensure_ascii=False)}")
        
        return summary
    
    else:
        print(f"[{category}] 이메일 모드가 아니므로 PowerAutomate로 전송하지 않습니다.")
        return {"category": category, "mode": mode, "status": "skipped"}

# 카테고리별 뉴스 처리 함수
def process_category_news(category, category_structure):
    """특정 카테고리의 뉴스를 처리합니다 (새로운 섹션 구조)"""
    print(f"\n====== {category} 카테고리 처리 시작 ======")
    
    # Store results for all companies in this category
    category_results = {}
    
    # Process each section in the category
    for section_name, companies in category_structure.items():
        print(f"\n--- {section_name} 섹션 처리 중 ---")
        
        # Process each company in the section
        for company in companies:
            # Get the keywords for this company
            company_keywords = COMPANY_KEYWORD_MAP.get(company, [company])
            
            # Process news for this company
            final_selection = process_company_news(company, company_keywords)
            
            # Store the results
            category_results[company] = final_selection
    
    print(f"====== {category} 카테고리 처리 완료 ======")
    return category_results

def format_sharepoint_hyperlink(url):
    """SharePoint 하이퍼링크 필드 형태로 URL을 포맷합니다."""
    if not url:
        return ""
    
    try:
        # SharePoint 하이퍼링크 필드 형태: {URL}
        return f"{url}"
    except Exception as e:
        print(f"하이퍼링크 포맷 중 오류: {str(e)}")
        return url

# 메인 함수
def main():
    """Main function to process news and send email"""
    print("====== 자동 뉴스 메일링 시작 ======")
    
    # 커맨드 라인 인자 처리
    github_actions_mode = False
    execution_mode = "email"  # 이메일 모드로 고정
    selected_categories = []  # 선택된 카테고리 저장
    
    # 인자 확인
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith('--mode='):
                mode = arg.split('=', 1)[1]
                if mode == "github-actions":
                    github_actions_mode = True
                    print("GitHub Actions 모드로 실행합니다.")
                elif mode == "email":
                    execution_mode = "email"
                    print("이메일 모드로 실행합니다.")
            elif arg.startswith('--categories='):
                # 카테고리 선택 처리 (쉼표로 구분)
                categories = arg.split('=', 1)[1].split(',')
                selected_categories = [cat.strip() for cat in categories if cat.strip() in COMPANY_CATEGORIES]
                print(f"선택된 카테고리: {selected_categories}")
    
    # 선택된 카테고리가 없으면 모든 카테고리 활성화
    if not selected_categories:
        selected_categories = list(COMPANY_CATEGORIES.keys())
    
    # 현재 날짜 가져오기
    current_date = get_current_date_str()
    
    # 선택된 카테고리만 처리
    all_summaries = {}
    
    # 선택된 카테고리만 실행
    for category in selected_categories:
        if category not in COMPANY_CATEGORIES:
            print(f"경고: {category}는 유효하지 않은 카테고리입니다. 건너뜁니다.")
            continue
            
        category_structure = COMPANY_CATEGORIES[category]  # 새로운 섹션 구조
        print(f"\n{'='*50}")
        print(f"카테고리: {category}")
        print(f"섹션 구조: {category_structure}")
        print(f"{'='*50}")
        
        # 카테고리별 뉴스 처리 (새로운 구조)
        category_results = process_category_news(category, category_structure)
        
        # GitHub Actions 모드인 경우 - PowerAutomate로만 전송하고 직접 이메일 발송하지 않음
        if github_actions_mode:
            print(f"\n====== {category} GitHub Actions 결과 출력 ======")
            summary = output_github_actions_result_by_category(category, category_results, category_structure, execution_mode)
            all_summaries[category] = summary
            print(f"{category} GitHub Actions 실행 완료 - PowerAutomate에서 이메일과 SharePoint를 처리합니다.")
        
        # 일반 모드 - 직접 이메일 발송
        else:
            category_email_settings = EMAIL_SETTINGS_BY_CATEGORY.get(category, EMAIL_SETTINGS_BY_CATEGORY["Corporate"])
            html_email_content = create_html_email_with_sections(category_results, category_structure, category)
            
            print(f"\n====== {category} 이메일 전송 시작 ======")
            print(f"수신자: {category_email_settings['to']}, 참조: {category_email_settings['cc']}")
            
            try:
                # 카테고리명 매핑 (Corporate -> GSP, Financial -> 금융GSP 및 주요 금융기업, 나머지는 그대로)
                if category == "Corporate":
                    category_display_name = "GSP"
                elif category == "Financial":
                    category_display_name = "금융GSP 및 주요 금융기업"
                else:
                    category_display_name = category
                success, response = send_email(
                    html_body=html_email_content,
                    to=category_email_settings["to"],
                    cc=category_email_settings["cc"],
                    # 한국 시간 기준으로 메일 제목 설정
                    subject=f"({datetime.now(KST).strftime('%m%d')}) Client Intelligence - {category_display_name}"
                )
                
                if success:
                    print(f"{category} 이메일이 성공적으로 전송되었습니다.")
                else:
                    response_text = response.text if hasattr(response, 'text') else "응답 내용 없음"
                    print(f"{category} 이메일 전송에 실패했습니다. 상태 코드: {getattr(response, 'status_code', '알 수 없음')}")
                    print(f"응답: {response_text}")
            except Exception as e:
                print(f"{category} 이메일 전송 중 오류 발생: {str(e)}")
            
            # SharePoint List 처리 (일반 모드에서만)
            print(f"\n====== {category} SharePoint List 처리 ======")
            sharepoint_success = process_sharepoint_list_by_category(category, category_results)
    
    # GitHub Actions 모드인 경우 전체 요약 반환
    if github_actions_mode:
        print("\n====== 전체 실행 완료 ======")
        print(f"처리된 카테고리: {list(all_summaries.keys())}")
        return all_summaries
    
    print("====== 자동 뉴스 메일링 완료 ======")

def test_html_email():
    """create_html_email_with_sections 함수를 테스트하는 함수"""
    print("====== HTML 이메일 테스트 시작 ======")
    
    # 테스트용 샘플 데이터 생성
    sample_category_results = {
        # Corporate - Anchor
        "삼성": [
            {
                "title": "삼성전자, 3분기 영업이익 전년 대비 50% 증가",
                "url": "https://example.com/news1",
                "date": "2024-10-25",
                "press": "한국경제"
            },
            {
                "title": "삼성그룹, 인도 진출 확대로 현지 합작회사 설립",
                "url": "https://example.com/news2", 
                "date": "2024-10-25",
                "press": "조선일보"
            }
        ],
        "SK": [
            {
                "title": "SK하이닉스, AI 메모리 반도체 수주 확대",
                "url": "https://example.com/news3",
                "date": "2024-10-25", 
                "press": "매일경제"
            }
        ],
        # Corporate - Growth_Whitespace  
        "HD현대": [
            {
                "title": "HD한국조선해양, 친환경 선박 대형 수주 성공",
                "url": "https://example.com/news4",
                "date": "2024-10-25",
                "press": "파이낸셜뉴스"
            }
        ],
        "CJ": [],  # 기사 없는 경우 테스트
        
        # Financial - 금융지주
        "KB금융": [
            {
                "title": "KB금융지주, 디지털 플랫폼 강화로 3분기 실적 개선",
                "url": "https://example.com/news5", 
                "date": "2024-10-25",
                "press": "연합뉴스"
            }
        ],
        "새마을금고등": [
            {
                "title": "새마을금고중앙회, 지역 금융 디지털화 추진",
                "url": "https://example.com/news6",
                "date": "2024-10-25",
                "press": "뉴시스"
            }
        ],
        
        # Financial - 핀테크
        "카카오뱅크": [
            {
                "title": "카카오뱅크, 대출 서비스 확대로 이용자 급증",
                "url": "https://example.com/news7",
                "date": "2024-10-25",
                "press": "이데일리"
            }
        ],
        "토스": [
            {
                "title": "토스뱅크, 새로운 금융 상품 출시 예정",
                "url": "https://example.com/news8",
                "date": "2024-10-25", 
                "press": "머니투데이"
            }
        ]
    }
    
    # 테스트용 카테고리 구조 (Financial)
    sample_category_structure_financial = {
        "금융지주": ["KB금융", "신한금융", "하나금융", "새마을금고등","NH금융","지방은행(iM금융 포함) 및 비은행 금융지주"],
        "비지주금융그룹": ["삼성(금융)", "한화(금융)"],
        "핀테크": ["카카오뱅크", "토스", "케이뱅크"]
    }
    
    # 테스트용 카테고리 구조 (Corporate)  
    sample_category_structure_corporate = {
        "Anchor": ["삼성", "SK", "LG", "현대차"],
        "Growth_Whitespace": ["HD현대", "CJ", "신세계", "GS"]
    }
    
    # Financial 카테고리 HTML 생성 및 저장
    print("Financial 카테고리 HTML 생성 중...")
    html_content_financial = create_html_email_with_sections(
        sample_category_results, 
        sample_category_structure_financial, 
        "Financial"
    )
    
    # HTML 파일로 저장
    with open("test_email_financial.html", "w", encoding="utf-8") as f:
        f.write(html_content_financial)
    print("Financial 카테고리 HTML이 test_email_financial.html로 저장되었습니다.")
    
    # Corporate 카테고리 HTML 생성 및 저장
    print("Corporate 카테고리 HTML 생성 중...")
    html_content_corporate = create_html_email_with_sections(
        sample_category_results,
        sample_category_structure_corporate, 
        "Corporate"
    )
    
    # HTML 파일로 저장
    with open("test_email_corporate.html", "w", encoding="utf-8") as f:
        f.write(html_content_corporate)
    print("Corporate 카테고리 HTML이 test_email_corporate.html로 저장되었습니다.")
    
    print("\n====== HTML 테스트 완료 ======")
    print("브라우저에서 다음 파일들을 열어서 확인하세요:")
    print("- test_email_financial.html")
    print("- test_email_corporate.html")
    print("특히 '새마을금고등'이 올바르게 '*새마을금고, IBK, 수협, 신협'으로 회색 글씨로 표시되는지 확인하세요.")

if __name__ == "__main__":
    # 커맨드 라인에서 --test-html 인자가 있으면 테스트 실행
    if len(sys.argv) > 1 and "--test-html" in sys.argv:
        test_html_email()
    else:
        main()