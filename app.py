import streamlit as st
import re


# ✅ 무조건 첫 Streamlit 명령어
st.set_page_config(
    page_title="PwC 뉴스 분석기",
    page_icon="📊",
    layout="wide",
)



from datetime import datetime, timedelta, timezone
import os
from PIL import Image
#import docx
#from docx.shared import Pt, RGBColor, Inches
import io
from urllib.parse import urlparse
from googlenews import GoogleNews
from news_ai import (
    collect_news,
    filter_valid_press,
    filter_excluded_keywords,  # 새로운 키워드 필터링 함수 추가
    filter_excluded_news,
    group_and_select_news,
    evaluate_importance,
)

# Import centralized configuration
from config import (
    COMPANY_CATEGORIES,
    COMPANY_KEYWORD_MAP,
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
    SYSTEM_PROMPT_3_BASE,  # 기본 템플릿 추가
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
    GPT_MODELS,
    DEFAULT_GPT_MODEL,
    # 새로 추가되는 회사별 기준들
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

def clean_title(title):
    """Clean title by removing the press name pattern at the end"""
    if not title:
        return ""
    # 0. [] 제거
    title = re.sub(r'^\s*\[.*?\]\s*', '', title).strip()  # 제목 맨 앞에만
    #title = re.sub(r'\[.*?\]', '', title).strip() # 제목 안에 다  
    # 1. 특정 패턴 먼저 처리: "- 조선비즈 - Chosun Biz" (정확히 이 문자열만)
    title = re.sub(r'\s*-\s*조선비즈\s*-\s*Chosun Biz\s*$', '', title, flags=re.IGNORECASE)
    
    # 1-2. 특정 패턴 처리: "- 조선비즈 - Chosunbiz" (B가 소문자인 경우)
    title = re.sub(r'\s*-\s*조선비즈\s*-\s*Chosunbiz\s*$', '', title, flags=re.IGNORECASE)
    
    # 2. 특정 패턴 처리: "- fnnews.com"
    title = re.sub(r'\s*-\s*fnnews\.com\s*$', '', title, flags=re.IGNORECASE)
    
    # 3. 일반적인 언론사 패턴 처리 (기존 로직)
    title = re.sub(r"\s*-\s*[가-힣A-Za-z0-9\s]+$", "", title).strip()
    
    return title.strip()

def create_pwc_html_email(all_results, selected_companies, selected_category=None, category_mode=None, main_category=None):
    """Create PwC-styled HTML email content from results with sections"""
    html_email_content = """
<div style="border-left: 6px solid #e03a3e; padding-left:16px; margin-bottom:24px; font-family:'맑은 고딕', Arial, sans-serif;">
  <div style="font-size:22px; color:#e03a3e; font-weight:bold; letter-spacing:0.5px;">PwC Client Intelligence</div>
  <div style="font-size:15px; color:#555; margin-top:10px;">안녕하세요, 좋은 아침입니다.<br>오늘의 <b>Client Intelligence</b>를 전달 드립니다.</div>
</div>

<div style="border-bottom:2px solid #e03a3e; margin-bottom:18px; padding-bottom:4px; font-size:16px; font-weight:600; color:#333; letter-spacing:0.3px;">
  [Client Intelligence]
</div>
"""
    
    # 통합 카테고리 모드인 경우 섹션별로 나누어서 표시 (auto_news_mail.py와 동일한 로직)
    if category_mode == "통합 카테고리" and main_category:
        # 카테고리 구조 가져오기
        category_structure = COMPANY_CATEGORIES.get(main_category, {})
        
        # 각 섹션별 처리
        for section_name, section_companies in category_structure.items():
            # 섹션에 포함된 회사 중 선택된 회사만 필터링
            selected_section_companies = [comp for comp in section_companies if comp in selected_companies]
            
            if not selected_section_companies:
                continue  # 선택된 회사가 없으면 섹션 건너뛰기
            
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
            
            # 지방은행 및 비은행 금융지주, 핀테크 섹션은 회사별 구분 없이 모든 기사를 하나의 목록으로 표출
            if section_name in ["핀테크"]:
                # 모든 회사의 기사들을 하나의 목록으로 수집 (중복 제거 포함)
                all_news_in_section = []
                seen_urls = set()
                seen_titles = set()
                
                for company in selected_section_companies:
                    news_list = all_results.get(company, [])
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
                # 기존 방식: 회사별 구분하여 표출 (Anchor, Growth_Whitespace, 금융지주, 비지주금융그룹)
                company_counter = 1
                for company in selected_section_companies:
                    # 새마을금고등의 경우 특별 처리 (제목 자체를 변경하고 회색으로 표시, 넘버링 없음)
                    if company == "새마을금고등":
                        company_display_name = "[상호금융 및 IBK]"
                        html_email_content += f"""
  <div style="margin-top:18px;">
    <div style="font-size:12px; color:#666; margin-bottom:6px; margin-top:2px;">
      {company_display_name}
    </div>"""
                    else:
                        # NH금융의 경우 특별 처리 (별표 추가)
                        company_display_name = f"{company}*" if company == "NH금융" else company
                        
                        html_email_content += f"""
  <div style="margin-top:18px;">
    <div style="font-size:15px; font-weight:bold; color:#004578; margin-bottom:6px; margin-top:20px;">
      {company_counter}. {company_display_name}
    </div>"""
                    
                        
                        # 지방은행 및 비은행 금융지주의 경우 제목 아래에 설명 추가
    #                     if company == "지방은행 및 비은행 금융지주":
    #                         html_email_content += """
    # <div style="font-size:12px; color:#666; margin-bottom:6px; margin-top:2px;">
    #   *IM금융 포함
    # </div>"""
                    
                    html_email_content += """
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
                    
                    # 새마을금고등과 지방은행 및 비은행 금융지주는 넘버링에서 제외하므로 카운터 증가하지 않음
                    if company not in ["새마을금고등"]:
                        company_counter += 1
            
            html_email_content += """
</div>"""
    
    else:
        # 개별 카테고리 모드: 기존 방식 (회사별 순서대로 나열)
        company_counter = 1
        for company in selected_companies:
            # 새마을금고등의 경우 특별 처리 (제목 자체를 변경하고 회색으로 표시, 넘버링 없음)
            if company == "새마을금고등":
                company_display_name = "[상호금융 및 IBK]"
                html_email_content += f"""
<div style="margin-top:18px;">
  <div style="font-size:12px; color:#666; margin-bottom:6px; margin-top:2px;">
    {company_display_name}
  </div>"""
            else:
                # NH금융의 경우 특별 처리 (별표 추가)
                company_display_name = company
                # company_display_name = f"{company}*" if company == "NH금융" else company
                
                html_email_content += f"""
<div style="margin-top:18px;">
  <div style="font-size:15px; font-weight:bold; color:#004578; margin-bottom:6px; margin-top:20px;">
    {company_counter}. {company_display_name}
  </div>"""
                
#                 # NH금융의 경우 주석 추가
#                 if company == "NH금융":
#                     html_email_content += """
#   <div style="font-size:12px; color:#666; margin-bottom:6px; margin-top:2px;">
#     [상호금융 및 IBK]
#   </div>"""
                
                # 지방은행 및 비은행 금융지주의 경우 제목 아래에 설명 추가
#                 if company == "지방은행 및 비은행 금융지주":
#                     html_email_content += """
#   <div style="font-size:12px; color:#666; margin-bottom:6px; margin-top:2px;">
#     *IM금융 포함
#   </div>"""
            
            html_email_content += """
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
            
            # 새마을금고등과 지방은행 및 비은행 금융지주는 넘버링에서 제외하므로 카운터 증가하지 않음
            if company not in ["새마을금고등"]:
                company_counter += 1
    
    # Corporate 카테고리인 경우 금융GSP 안내 문구 추가
    gsp_notice = ""
    if selected_category and selected_category.lower() == "corporate":
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
</div>"""
    
    return html_email_content

# 회사별 추가 기준을 적용하는 함수들
def get_enhanced_exclusion_criteria(companies, base_criteria=None):
    """회사별 제외 기준을 추가한 프롬프트 반환 (여러 회사 지원)"""
    # 사용자 수정 기준이 없으면 카테고리별 기본 기준 사용
    if base_criteria is None:
        # companies가 문자열이면 리스트로 변환
        if isinstance(companies, str):
            companies = [companies]
        
        # 첫 번째 회사의 카테고리를 기준으로 제외 기준 결정
        if companies:
            main_category = get_main_category_for_company(companies[0])
            base_criteria = get_exclusion_criteria_for_category(main_category)
        else:
            base_criteria = EXCLUSION_CRITERIA
    
    # companies가 문자열이면 리스트로 변환
    if isinstance(companies, str):
        companies = [companies]
    
    # 회사별 키워드 정보를 동적으로 추가
    company_keywords_info = "\n\n[분석 대상 기업별 키워드 목록]\n"
    for company in companies:
        keywords = COMPANY_KEYWORD_MAP.get(company, [company])
        company_keywords_info += f"• {company}: {', '.join(keywords)}\n"
    
    # 키워드 연관성 체크 기준을 동적으로 업데이트
    updated_criteria = base_criteria.replace(
        "• 각 회사별 키워드 목록은 COMPANY_KEYWORD_MAP 참조",
        f"• 해당 기업의 키워드: {company_keywords_info.strip()}"
    )
    
    # 선택된 모든 회사의 추가 기준을 합침
    all_additional_criteria = ""
    for company in companies:
        # 세션 상태에서 사용자 수정 기준 가져오기
        if 'company_additional_exclusion_criteria' in st.session_state:
            additional_criteria = st.session_state.company_additional_exclusion_criteria.get(company, "")
        else:
            additional_criteria = COMPANY_ADDITIONAL_EXCLUSION_CRITERIA.get(company, "")
        if additional_criteria:
            all_additional_criteria += additional_criteria
    
    return updated_criteria + all_additional_criteria

def get_enhanced_duplicate_handling(companies, base_criteria=None):
    """회사별 중복 처리 기준을 추가한 프롬프트 반환 (여러 회사 지원)"""
    # 사용자 수정 기준이 없으면 기본 기준 사용
    if base_criteria is None:
        base_criteria = DUPLICATE_HANDLING
    
    # companies가 문자열이면 리스트로 변환
    if isinstance(companies, str):
        companies = [companies]
    
    # 선택된 모든 회사의 추가 기준을 합침
    all_additional_criteria = ""
    for company in companies:
        # 세션 상태에서 사용자 수정 기준 가져오기
        if 'company_additional_duplicate_handling' in st.session_state:
            additional_criteria = st.session_state.company_additional_duplicate_handling.get(company, "")
        else:
            additional_criteria = COMPANY_ADDITIONAL_DUPLICATE_HANDLING.get(company, "")
        if additional_criteria:
            all_additional_criteria += additional_criteria
    
    return base_criteria + all_additional_criteria

def get_enhanced_selection_criteria(companies, base_criteria=None):
    """회사별 선택 기준을 추가한 프롬프트 반환 (여러 회사 지원)"""
    # 사용자 수정 기준이 없으면 기본 기준 사용
    if base_criteria is None:
        base_criteria = SELECTION_CRITERIA
    
    # companies가 문자열이면 리스트로 변환
    if isinstance(companies, str):
        companies = [companies]
    
    # 회사별 키워드 정보를 동적으로 추가
    company_keywords_info = "\n\n[분석 대상 기업별 키워드 목록]\n"
    for company in companies:
        keywords = COMPANY_KEYWORD_MAP.get(company, [company])
        company_keywords_info += f"• {company}: {', '.join(keywords)}\n"
    
    # 키워드 연관성 체크 기준을 동적으로 업데이트
    updated_criteria = base_criteria.replace(
        "• 각 회사별 키워드 목록은 COMPANY_KEYWORD_MAP 참조",
        f"• 해당 기업의 키워드: {company_keywords_info.strip()}"
    )
    
    # 선택된 모든 회사의 추가 기준을 합침
    all_additional_criteria = ""
    for company in companies:
        # 세션 상태에서 사용자 수정 기준 가져오기
        if 'company_additional_selection_criteria' in st.session_state:
            additional_criteria = st.session_state.company_additional_selection_criteria.get(company, "")
        else:
            additional_criteria = COMPANY_ADDITIONAL_SELECTION_CRITERIA.get(company, "")
        if additional_criteria:
            all_additional_criteria += additional_criteria
    
    return updated_criteria + all_additional_criteria
            
# 워드 파일 생성 함수
# def create_word_document(keyword, final_selection, analysis=""):
#     # 새 워드 문서 생성
#     doc = docx.Document()
    
#     # 제목 스타일 설정
#     title = doc.add_heading(f'PwC 뉴스 분석 보고서: {keyword}', level=0)
#     for run in title.runs:
#         run.font.color.rgb = RGBColor(208, 74, 2)  # PwC 오렌지 색상
    
#     # 분석 요약 추가
#     if analysis:
#         doc.add_heading('회계법인 관점의 분석 결과', level=1)
#         doc.add_paragraph(analysis)
    
#     # 선별된 주요 뉴스 추가
#     doc.add_heading('선별된 주요 뉴스', level=1)
    
#     for i, news in enumerate(final_selection):
#         p = doc.add_paragraph()
#         p.add_run(f"{i+1}. {news['title']}").bold = True
        
#         # 날짜 정보 추가
#         date_str = news.get('date', '날짜 정보 없음')
#         date_paragraph = doc.add_paragraph()
#         date_paragraph.add_run(f"날짜: {date_str}").italic = True
        
#         # 선정 사유 추가
#         reason = news.get('reason', '')
#         if reason:
#             doc.add_paragraph(f"선정 사유: {reason}")
        
#         # 키워드 추가
#         keywords = news.get('keywords', [])
#         if keywords:
#             doc.add_paragraph(f"키워드: {', '.join(keywords)}")
        
#         # 관련 계열사 추가
#         affiliates = news.get('affiliates', [])
#         if affiliates:
#             doc.add_paragraph(f"관련 계열사: {', '.join(affiliates)}")
        
#         # 언론사 추가
#         press = news.get('press', '알 수 없음')
#         doc.add_paragraph(f"언론사: {press}")
        
#         # URL 추가
#         url = news.get('url', '')
#         if url:
#             doc.add_paragraph(f"출처: {url}")
        
#         # 구분선 추가
#         if i < len(final_selection) - 1:
#             doc.add_paragraph("").add_run().add_break()
    
#     # 날짜 및 푸터 추가
#     current_date = datetime.now().strftime("%Y년 %m월 %d일")
#     doc.add_paragraph(f"\n보고서 생성일: {current_date}")
#     doc.add_paragraph("© 2024 PwC 뉴스 분석기 | 회계법인 관점의 뉴스 분석 도구")
    
#     return doc

# BytesIO 객체로 워드 문서 저장
def get_binary_file_downloader_html(doc, file_name):
    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio

# 커스텀 CSS
st.markdown("""
<style>
    .title-container {
        display: flex;
        align-items: center;
        gap: 20px;
        margin-bottom: 20px;
    }
    .main-title {
        color: #d04a02;
        font-size: 2.5rem;
        font-weight: 700;
    }
    .news-card {
        background-color: #f9f9f9;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 15px;
        border-left: 4px solid #d04a02;
    }
    .news-title {
        font-weight: 600;
        font-size: 1.1rem;
    }
    .news-url {
        color: #666;
        font-size: 0.9rem;
    }
    .news-date {
        color: #666;
        font-size: 0.9rem;
        font-style: italic;
        margin-top: 5px;
    }
    .analysis-box {
        background-color: #f5f5ff;
        border-radius: 10px;
        padding: 20px;
        margin: 20px 0;
        border-left: 4px solid #d04a02;
    }
    .subtitle {
        color: #dc582a;
        font-size: 1.3rem;
        font-weight: 600;
        margin-top: 20px;
        margin-bottom: 10px;
    }
    .download-box {
        background-color: #eaf7f0;
        border-radius: 10px;
        padding: 20px;
        margin: 20px 0;
        border-left: 4px solid #00a36e;
        text-align: center;
    }
    .analysis-section {
        background-color: #f8f9fa;
        border-left: 4px solid #d04a02;
        padding: 20px;
        margin: 10px 0;
        border-radius: 5px;
    }
    .selected-news {
        border-left: 4px solid #0077b6;
        padding: 15px;
        margin: 10px 0;
        background-color: #f0f8ff;
        border-radius: 5px;
    }
    .excluded-news {
        color: #666;
        padding: 5px 0;
        margin: 5px 0;
        font-size: 0.9em;
    }
    .news-meta {
        color: #666;
        font-size: 0.9em;
        margin: 3px 0;
    }
    .selection-reason {
        color: #666;
        margin: 5px 0;
        font-size: 0.95em;
    }
    .keywords {
        color: #666;
        font-size: 0.9em;
        margin: 5px 0;
    }
    .affiliates {
        color: #666;
        font-size: 0.9em;
        margin: 5px 0;
    }
    .news-url {
        color: #0077b6;
        font-size: 0.9em;
        margin: 5px 0;
        word-break: break-all;
    }
    .news-title-large {
        font-size: 1.2em;
        font-weight: 600;
        color: #000;
        margin-bottom: 8px;
        line-height: 1.4;
    }
    .news-url {
        color: #0077b6;
        font-size: 0.9em;
        margin: 5px 0 10px 0;
        word-break: break-all;
    }
    .news-summary {
        color: #444;
        font-size: 0.95em;
        margin: 10px 0;
        line-height: 1.4;
    }
    .selection-reason {
        color: #666;
        font-size: 0.95em;
        margin: 10px 0;
        line-height: 1.4;
    }
    .importance-high {
        color: #d04a02;
        font-weight: 700;
        margin: 5px 0;
    }
    .importance-medium {
        color: #0077b6;
        font-weight: 700;
        margin: 5px 0;
    }
    .group-indices {
        color: #666;
        font-size: 0.9em;
    }
    .group-selected {
        color: #00a36e;
        font-weight: 600;
    }
    .group-reason {
        color: #666;
        font-size: 0.9em;
        margin-top: 5px;
    }
    .not-selected-news {
        color: #666;
        padding: 5px 0;
        margin: 5px 0;
        font-size: 0.9em;
    }
    .importance-low {
        color: #666;
        font-weight: 700;
        margin: 5px 0;
    }
    .not-selected-reason {
        color: #666;
        margin: 5px 0;
        font-size: 0.95em;
    }
    .email-preview {
        background-color: white;
        border: 1px solid #ddd;
        border-radius: 5px;
        padding: 20px;
        margin: 20px 0;
        overflow-y: auto;
        max-height: 500px;
    }
    .copy-button {
        background-color: #d04a02;
        color: white;
        padding: 10px 20px;
        border: none;
        border-radius: 5px;
        cursor: pointer;
        margin: 10px 0;
    }
    .copy-button:hover {
        background-color: #b33d00;
    }
</style>
""", unsafe_allow_html=True)

# 로고와 제목
col1, col2 = st.columns([1, 5])
with col1:
    # 로고 표시
    logo_path = "pwc_logo.png"
    if os.path.exists(logo_path):
        st.image(logo_path, width=100)
    else:
        st.error("로고 파일을 찾을 수 없습니다. 프로젝트 루트에 'pwc_logo.png' 파일을 추가해주세요.")

with col2:
    st.markdown("<h1 class='main-title'>PwC 뉴스 분석기</h1>", unsafe_allow_html=True)
    st.markdown("회계법인 관점에서 중요한 뉴스를 자동으로 분석하는 AI 도구")

# 기본 선택 카테고리를 Corporate로 설정하고 회사 목록을 평면화
def get_companies_from_category(category):
    """카테고리에서 모든 회사 목록을 평면화하여 반환"""
    if category not in COMPANY_CATEGORIES:
        return []
    
    category_structure = COMPANY_CATEGORIES[category]
    if isinstance(category_structure, dict):
        # 새로운 섹션 구조인 경우 평면화
        companies = []
        for section_companies in category_structure.values():
            companies.extend(section_companies)
        return companies
    else:
        # 기존 리스트 구조인 경우 그대로 반환
        return category_structure

def get_companies_from_subcategory(subcategory):
    """하위 카테고리에서 회사 목록을 반환"""
    subcategory_mapping = {
        "Anchor": COMPANY_CATEGORIES["Corporate"]["Anchor"],
        "Growth & Whitespace": COMPANY_CATEGORIES["Corporate"]["Growth_Whitespace"], 
        "금융지주": COMPANY_CATEGORIES["Financial"]["금융지주"],
        "비지주 금융그룹": COMPANY_CATEGORIES["Financial"]["비지주금융그룹"],
        "핀테크": COMPANY_CATEGORIES["Financial"]["핀테크"]
    }
    return subcategory_mapping.get(subcategory, [])

def get_parent_category_from_subcategory(subcategory):
    """하위 카테고리에서 상위 카테고리를 반환"""
    if subcategory in ["Anchor", "Growth & Whitespace"]:
        return "Corporate"
    elif subcategory in ["금융지주", "비지주 금융그룹", "핀테크"]:
        return "Financial"
    return None

def get_company_category(company):
    """
    회사명으로부터 해당하는 카테고리를 찾는 함수
    
    Args:
        company (str): 회사명
    
    Returns:
        str: 카테고리명 (Anchor, Growth_Whitespace, 5대금융지주, 인터넷뱅크)
    """
    for main_category, sub_categories in COMPANY_CATEGORIES.items():
        for category, companies in sub_categories.items():
            if company in companies:
                return category
    return "Anchor"  # 기본값

# 기본 선택을 Anchor로 설정
COMPANIES = get_companies_from_subcategory("Anchor")

# 사이드바 설정
st.sidebar.title("🔍 분석 설정")

# 0단계: 기본 설정
st.sidebar.markdown("### 📋 0단계: 기본 설정")

# 유효 언론사 설정 (기본값으로 Corporate 사용)
valid_press_dict = st.sidebar.text_area(
    "📰 유효 언론사 설정",
    value="""조선일보: ["조선일보", "chosun", "chosun.com"]
    중앙일보: ["중앙일보", "joongang", "joongang.co.kr", "joins.com"]
    동아일보: ["동아일보", "donga", "donga.com"]
    조선비즈: ["조선비즈", "chosunbiz", "biz.chosun.com"]
    매거진한경: ["매거진한경", "magazine.hankyung", "magazine.hankyung.com"]
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
    헤럴드경제: ["헤럴드경제", "herald", "heraldcorp", "heraldcorp.com"]
    더벨: ["더벨", "thebell", "thebell.co.kr"]""",
    help="분석에 포함할 신뢰할 수 있는 언론사와 그 별칭을 설정하세요. 형식: '언론사: [별칭1, 별칭2, ...]'",
    key="valid_press_dict"
)

# 추가 언론사 설정 (재평가 시에만 사용됨)
additional_press_dict = st.sidebar.text_area(
    "📰 추가 언론사 설정 (재평가 시에만 사용)",
    value="""철강금속신문: ["철강금속신문", "snmnews", "snmnews.com"]
    에너지신문: ["에너지신문", "energy-news", "energy-news.co.kr"]
    이코노믹데일리: ["이코노믹데일리", "economidaily", "economidaily.com"]""",
    help="기본 언론사에서 뉴스가 선택되지 않을 경우, 재평가 단계에서 추가로 고려할 언론사와 별칭을 설정하세요. 형식: '언론사: [별칭1, 별칭2, ...]'",
    key="additional_press_dict"
)



# 구분선 추가
st.sidebar.markdown("---")

# 날짜 필터 설정
st.sidebar.markdown("### 📅 날짜 필터")

# 현재 시간 가져오기
now = datetime.now()

# 기본 시작 날짜/시간 계산 - 월요일 특별 처리
if now.weekday() == 0:  # 월요일 (0=월요일)
    # 월요일: 토요일부터 검색 (토, 일, 월) - Financial 카테고리 고려
    default_start_date = now - timedelta(days=2)  # 2일 전 (토요일)
else:
    # 기본: 어제부터 검색
    default_start_date = now - timedelta(days=1)

# Set time to 8:00 AM for both start and end - 한국 시간 기준
start_datetime = datetime.combine(default_start_date.date(), 
                                    datetime.strptime("08:00", "%H:%M").time(), KST)
end_datetime = datetime.combine(now.date(), 
                                datetime.strptime("08:00", "%H:%M").time(), KST)

col1, col2 = st.sidebar.columns(2)
with col1:
    start_date = st.date_input(
        "시작 날짜",
        value=default_start_date.date(),
        help="이 날짜부터 뉴스를 검색합니다. 월요일인 경우 토요일부터 검색 (토, 일, 월) - Financial 카테고리 고려, 그 외에는 전일부터 검색합니다."
    )
    start_time = st.time_input(
        "시작 시간",
        value=start_datetime.time(),
        help="시작 날짜의 구체적인 시간을 설정합니다. 기본값은 오전 8시입니다."
    )
with col2:
    end_date = st.date_input(
        "종료 날짜",
        value=now.date(),
        help="이 날짜까지의 뉴스를 검색합니다."
    )
    end_time = st.time_input(
        "종료 시간",
        value=end_datetime.time(),
        help="종료 날짜의 구체적인 시간을 설정합니다. 기본값은 오전 8시입니다."
    )

# 구분선 추가
st.sidebar.markdown("---")

# 1단계: 제외 판단 기준

# 기업 선택 섹션 제목
st.sidebar.markdown("### 🏢 분석할 기업 선택")

# 카테고리 선택 방식 선택
category_mode = st.sidebar.radio(
    "카테고리 선택 방식",
    options=["개별 카테고리", "통합 카테고리"],
    index=0,
    help="• 개별 카테고리: 세부 카테고리별로 선택 (Anchor, Growth & Whitespace 등)\n• 통합 카테고리: 대분류로 선택 (Corporate 전체, Financial 전체)"
)

if category_mode == "개별 카테고리":
    # 기존 방식: 개별 카테고리 선택
    selected_subcategory = st.sidebar.radio(
        "기업 카테고리를 선택하세요",
        options=["Anchor", "Growth & Whitespace", "금융지주", "비지주 금융그룹", "핀테크"],
        index=0,  # Anchor를 기본값으로 설정
        help="분석할 기업 카테고리를 선택하세요.\n• Anchor: 삼성, SK, LG, 현대차, 롯데, 한화, 포스코\n• Growth & Whitespace: HD현대, 신세계, GS, LS, CJ\n• 금융지주: KB, 신한, 우리, 하나, NH\n• 비지주 금융그룹: 삼성(금융), 한화(금융), 미래에셋 등\n• 핀테크: 카카오뱅크, 토스, 케이뱅크"
    )
    
    # 선택된 하위 카테고리에 따라 COMPANIES 업데이트
    COMPANIES = get_companies_from_subcategory(selected_subcategory)
    
    # 상위 카테고리 정보 가져오기 (새로운 기업 추가 시 필요)
    selected_category = get_parent_category_from_subcategory(selected_subcategory)
    
else:
    # 새로운 방식: 통합 카테고리 선택
    selected_main_category = st.sidebar.radio(
        "통합 카테고리를 선택하세요",
        options=["Corporate", "Financial"],
        index=0,  # Corporate를 기본값으로 설정
        help="• Corporate: Anchor + Growth & Whitespace (삼성, SK, LG, 현대차, 롯데, 한화, 포스코, HD현대, 신세계, GS, LS, CJ)\n• Financial: 금융지주 + 비지주 금융그룹 + 핀테크 (모든 금융 관련 기업)"
    )
    
    # 통합 카테고리에 따라 COMPANIES 업데이트
    COMPANIES = get_companies_from_category(selected_main_category)
    
    # 선택된 카테고리 정보 설정
    selected_category = selected_main_category
    selected_subcategory = selected_main_category  # 통합 모드에서는 메인 카테고리가 서브카테고리 역할

# 새로운 기업 추가 섹션
new_company = st.sidebar.text_input(
    "새로운 기업 추가",
    value="",
    help="분석하고 싶은 기업명을 입력하고 Enter를 누르세요. (예: 네이버, 카카오, 현대중공업 등)"
)

# 새로운 기업 추가 로직 - 카테고리 모드에 따라 처리
if new_company and new_company not in COMPANIES:
    if category_mode == "개별 카테고리":
        # 개별 카테고리 모드: 기존 로직
        subcategory_key_mapping = {
            "Anchor": ("Corporate", "Anchor"),
            "Growth & Whitespace": ("Corporate", "Growth_Whitespace"),
            "금융지주": ("Financial", "금융지주"),
            "비지주 금융그룹": ("Financial", "비지주금융그룹"),
            "핀테크": ("Financial", "핀테크")
        }
        
        if selected_subcategory in subcategory_key_mapping:
            parent_cat, section_key = subcategory_key_mapping[selected_subcategory]
            COMPANY_CATEGORIES[parent_cat][section_key].append(new_company)
            
            # 세션 상태의 카테고리도 업데이트
            if 'company_categories' in st.session_state:
                st.session_state.company_categories[parent_cat][section_key].append(new_company)
            
            # COMPANIES 리스트도 업데이트
            COMPANIES = get_companies_from_subcategory(selected_subcategory)
            
    else:
        # 통합 카테고리 모드: 어떤 하위 카테고리에 추가할지 선택
        if selected_main_category == "Corporate":
            subcategory_options = ["Anchor", "Growth_Whitespace"]
            subcategory_display = ["Anchor", "Growth & Whitespace"]
        else:  # Financial
            subcategory_options = ["금융지주", "비지주금융그룹", "핀테크"]
            subcategory_display = ["금융지주", "비지주 금융그룹", "핀테크"]
        
        # 하위 카테고리 선택
        target_subcategory = st.sidebar.selectbox(
            f"'{new_company}'를 추가할 하위 카테고리 선택",
            options=subcategory_display,
            help=f"{selected_main_category} 카테고리 내에서 새 기업을 추가할 세부 카테고리를 선택하세요."
        )
        
        # 선택된 하위 카테고리에 추가
        subcategory_key = subcategory_options[subcategory_display.index(target_subcategory)]
        COMPANY_CATEGORIES[selected_main_category][subcategory_key].append(new_company)
        
        # 세션 상태의 카테고리도 업데이트
        if 'company_categories' in st.session_state:
            st.session_state.company_categories[selected_main_category][subcategory_key].append(new_company)
        
        # COMPANIES 리스트도 업데이트
        COMPANIES = get_companies_from_category(selected_main_category)
    
    # 새 기업에 대한 기본 연관 키워드 설정 (기업명 자체만 포함)
    COMPANY_KEYWORD_MAP[new_company] = [new_company]
    # 세션 상태도 함께 업데이트
    if 'company_keyword_map' in st.session_state:
        st.session_state.company_keyword_map[new_company] = [new_company]

# 키워드 선택을 multiselect로 변경 - 카테고리 모드에 따라 조정
if category_mode == "개별 카테고리":
    # 개별 카테고리: 최대 10개, 기본 선택 처음 10개
    max_selections = 10
    default_selection = COMPANIES[:10]
    help_text = "분석하고자 하는 기업을 선택하세요. 한 번에 최대 10개까지 선택 가능합니다."
else:
    # 통합 카테고리: 최대 20개, 기본 선택 처음 15개 (더 많은 회사가 있을 수 있으므로)
    max_selections = 20
    default_selection = COMPANIES[:15] if len(COMPANIES) >= 15 else COMPANIES
    help_text = f"통합 카테고리에서 분석하고자 하는 기업을 선택하세요. 한 번에 최대 {max_selections}개까지 선택 가능합니다."

selected_companies = st.sidebar.multiselect(
    f"분석할 기업을 선택하세요 (최대 {max_selections}개)",
    options=COMPANIES,
    default=default_selection,
    max_selections=max_selections,
    help=help_text
)

# 제외 키워드 설정 - 선택된 회사들의 카테고리에 따라 기본값 결정
default_keywords = []
if selected_companies:
    # 선택된 회사들의 main category 확인
    main_categories = set()
    for company in selected_companies:
        main_category = get_main_category_for_company(company)
        main_categories.add(main_category)
    
    # Financial 카테고리가 포함되어 있으면 Financial 키워드 사용
    if "Financial" in main_categories:
        default_keywords = get_excluded_keywords_for_category("Financial")
    else:
        default_keywords = get_excluded_keywords_for_category("Corporate")
else:
    # 회사가 선택되지 않은 경우 기본값 사용
    default_keywords = EXCLUDED_KEYWORDS

excluded_keywords_text = st.sidebar.text_area(
    "🚫 Rule 기반 제외 키워드 설정",
    value=", ".join(default_keywords),
    help="특정 키워드가 포함된 기사를 자동으로 제외하는 키워드 목록입니다. 쉼표(,)로 구분하여 입력하세요. 선택된 회사 카테고리에 따라 기본값이 자동 설정됩니다.",
    key="excluded_keywords_text"
)

# 제외 키워드를 리스트로 변환
excluded_keywords_list = [kw.strip() for kw in excluded_keywords_text.split(",") if kw.strip()]

# 선택된 회사에 따른 카테고리별 언론사 설정 안내
if selected_companies:
    # 선택된 회사들의 main category 확인
    main_categories = set()
    for company in selected_companies:
        main_category = get_main_category_for_company(company)
        main_categories.add(main_category)
    
    # Financial 카테고리가 포함되어 있으면 안내 메시지 표시
    if "Financial" in main_categories:
        st.sidebar.info("💡 **언론사 설정 안내**: 선택된 회사에 Financial 카테고리가 포함되어 있습니다. 필요 시 언론사 설정에 'SBS: [\"SBS\", \"sbs\", \"sbs.co.kr\"]', 'MBC: [\"MBC\", \"mbc\", \"mbc.co.kr\"]', 'KBS: [\"KBS\", \"kbs\", \"kbs.co.kr\"]'을 추가하실 수 있습니다.")

# 제외 키워드 미리보기
with st.sidebar.expander("🔍 제외 키워드 미리보기"):
    if selected_companies:
        # 선택된 회사들의 카테고리 정보 표시
        company_categories_info = {}
        for company in selected_companies:
            main_category = get_main_category_for_company(company)
            if main_category not in company_categories_info:
                company_categories_info[main_category] = []
            company_categories_info[main_category].append(company)
        
        st.markdown("**선택된 회사 카테고리:**")
        for main_category, companies in company_categories_info.items():
            company_names = ", ".join(companies[:3])  # 최대 3개만 표시
            if len(companies) > 3:
                company_names += f" 외 {len(companies)-3}개"
            st.write(f"• {main_category}: {company_names}")
        
        # Financial 카테고리 포함 여부에 따른 키워드 정책 설명
        if "Financial" in company_categories_info:
            st.info("💡 Financial 카테고리가 포함되어 Rule 기반 키워드 필터링이 적용됩니다.")
        else:
            st.info("💡 Corporate 전용 선택으로 Rule 기반 키워드 필터링이 비활성화됩니다.")
        
        st.markdown("---")
    
    if excluded_keywords_list:
        st.markdown("**현재 설정된 제외 키워드:**")
        for i, keyword in enumerate(excluded_keywords_list, 1):
            st.write(f"{i}. {keyword}")
        st.markdown(f"**총 {len(excluded_keywords_list)}개 키워드가 설정되어 있습니다.**")
    else:
        st.info("설정된 제외 키워드가 없습니다.")

# 연관 키워드 관리 섹션
st.sidebar.markdown("### 🔍 연관 키워드 관리")
st.sidebar.markdown("각 기업의 연관 키워드를 확인하고 편집할 수 있습니다.")

# 세션 상태에 COMPANY_KEYWORD_MAP 및 COMPANY_CATEGORIES 저장 (초기화)
if 'company_keyword_map' not in st.session_state:
    st.session_state.company_keyword_map = COMPANY_KEYWORD_MAP.copy()
    
# 세션 상태에 회사 카테고리 저장 (초기화)
if 'company_categories' not in st.session_state:
    st.session_state.company_categories = COMPANY_CATEGORIES.copy()
else:
    # 세션에 저장된 카테고리 정보가 있으면 사용
    COMPANY_CATEGORIES = st.session_state.company_categories
    # 선택된 하위 카테고리에 따라 COMPANIES 다시 업데이트
    COMPANIES = get_companies_from_subcategory(selected_subcategory)

# 연관 키워드 UI 개선
if selected_companies:
    # 선택된 기업 중에서 관리할 기업 선택
    company_to_edit = st.sidebar.selectbox(
        "연관 키워드를 관리할 기업 선택",
        options=selected_companies,
        help="키워드를 확인하거나 추가할 기업을 선택하세요."
    )
    
    if company_to_edit:
        # 현재 연관 키워드 표시 (세션 상태에서 가져옴)
        current_keywords = st.session_state.company_keyword_map.get(company_to_edit, [company_to_edit])
        st.sidebar.markdown(f"**현재 '{company_to_edit}'의 연관 키워드:**")
        keyword_list = ", ".join(current_keywords)
        st.sidebar.code(keyword_list)
        
        # 연관 키워드 편집
        new_keywords = st.sidebar.text_area(
            "연관 키워드 편집",
            value=keyword_list,
            help="쉼표(,)로 구분하여 키워드를 추가/편집하세요.",
            key=f"edit_{company_to_edit}"  # 고유 키 추가
        )
        
        # 키워드 업데이트 함수
        def update_keywords():
            # 쉼표로 구분된 텍스트를 리스트로 변환
            updated_keywords = [kw.strip() for kw in new_keywords.split(",") if kw.strip()]
            
            # 업데이트
            if updated_keywords:
                st.session_state.company_keyword_map[company_to_edit] = updated_keywords
                st.sidebar.success(f"'{company_to_edit}'의 연관 키워드가 업데이트되었습니다!")
            else:
                # 비어있으면 기업명 자체만 포함
                st.session_state.company_keyword_map[company_to_edit] = [company_to_edit]
                st.sidebar.warning(f"연관 키워드가 비어있어 기업명만 포함됩니다.")
        
        # 변경 사항 적용 버튼
        if st.sidebar.button("연관 키워드 업데이트", key=f"update_{company_to_edit}", on_click=update_keywords):
            pass  # 실제 업데이트는 on_click에서 처리되므로 여기서는 아무것도 하지 않음

# 미리보기 버튼 - 모든 검색어 확인
with st.sidebar.expander("🔍 전체 검색 키워드 미리보기"):
    # 선택된 카테고리 정보 표시 - 카테고리 모드에 따라 구분
    if category_mode == "개별 카테고리":
        st.markdown(f"**📂 선택된 카테고리**: {selected_subcategory} (개별 모드)")
    else:
        st.markdown(f"**📂 선택된 카테고리**: {selected_main_category} (통합 모드)")
        # 통합 모드에서는 포함된 하위 카테고리도 표시
        if selected_main_category == "Corporate":
            st.markdown("**📋 포함 하위 카테고리**: Anchor + Growth & Whitespace")
        else:
            st.markdown("**📋 포함 하위 카테고리**: 금융지주 + 비지주 금융그룹 + 핀테크")
    
    st.markdown(f"📌 **포함된 회사**: {', '.join(COMPANIES)}")
    st.markdown("---")
    
    # 선택된 회사들의 키워드 미리보기
    st.markdown("**🔍 선택된 회사들의 검색 키워드:**")
    for i, company in enumerate(selected_companies, 1):
        # 세션 상태에서 키워드 가져오기
        company_keywords = st.session_state.company_keyword_map.get(company, [company])
        st.markdown(f"**{i}. {company}**")
        # 연관 키워드 표시
        for j, kw in enumerate(company_keywords, 1):
            st.write(f"  {j}) {kw}")

# 선택된 키워드들을 통합 (검색용)
keywords = []
for company in selected_companies:
    # 기업명 자체와 연관 키워드 모두 추가 (세션 상태에서 가져옴)
    company_keywords = st.session_state.company_keyword_map.get(company, [company])
    keywords.extend(company_keywords)

# 중복 제거
keywords = list(set(keywords))

# 구분선 추가
st.sidebar.markdown("---")

# 회사별 특화 기준 관리 섹션
st.sidebar.markdown("### 🎯 회사별 특화 기준 관리")
st.sidebar.markdown("각 기업의 AI 분석 특화 기준을 확인하고 편집할 수 있습니다.")

# 회사별 특화 기준 관리 UI
if selected_companies:
    # 선택된 기업 중에서 관리할 기업 선택
    company_to_manage = st.sidebar.selectbox(
        "특화 기준을 관리할 기업 선택",
        options=selected_companies,
        help="AI 분석 특화 기준을 확인하거나 편집할 기업을 선택하세요.",
        key="company_to_manage"
    )
    
    if company_to_manage:
        # 탭 형태로 1~3단계 기준을 구분
        criteria_tabs = st.sidebar.radio(
            f"'{company_to_manage}' 특화 기준 선택",
            ["1단계: 제외 기준", "2단계: 그룹핑 기준", "3단계: 선택 기준"],
            key=f"criteria_tabs_{company_to_manage}"
        )
        
        # 세션 상태에서 회사별 특화 기준 관리 (초기화)
        if 'company_additional_exclusion_criteria' not in st.session_state:
            st.session_state.company_additional_exclusion_criteria = COMPANY_ADDITIONAL_EXCLUSION_CRITERIA.copy()
        if 'company_additional_duplicate_handling' not in st.session_state:
            st.session_state.company_additional_duplicate_handling = COMPANY_ADDITIONAL_DUPLICATE_HANDLING.copy()
        if 'company_additional_selection_criteria' not in st.session_state:
            st.session_state.company_additional_selection_criteria = COMPANY_ADDITIONAL_SELECTION_CRITERIA.copy()
        
        if criteria_tabs == "1단계: 제외 기준":
            current_criteria = st.session_state.company_additional_exclusion_criteria.get(company_to_manage, "")
            st.sidebar.markdown(f"**현재 '{company_to_manage}'의 제외 특화 기준:**")
            if current_criteria.strip():
                st.sidebar.code(current_criteria, language="text")
            else:
                st.sidebar.info("설정된 특화 기준이 없습니다.")
            
            # 편집 영역
            new_exclusion_criteria = st.sidebar.text_area(
                "제외 특화 기준 편집",
                value=current_criteria,
                help="이 회사에만 적용될 추가 제외 기준을 입력하세요.",
                key=f"edit_exclusion_{company_to_manage}",
                height=150
            )
            
            # 업데이트 함수
            def update_exclusion_criteria():
                st.session_state.company_additional_exclusion_criteria[company_to_manage] = new_exclusion_criteria
                st.sidebar.success(f"'{company_to_manage}'의 제외 특화 기준이 업데이트되었습니다!")
            
            # 업데이트 버튼
            if st.sidebar.button("제외 기준 업데이트", key=f"update_exclusion_{company_to_manage}", on_click=update_exclusion_criteria):
                pass
                
        elif criteria_tabs == "2단계: 그룹핑 기준":
            current_criteria = st.session_state.company_additional_duplicate_handling.get(company_to_manage, "")
            st.sidebar.markdown(f"**현재 '{company_to_manage}'의 그룹핑 특화 기준:**")
            if current_criteria.strip():
                st.sidebar.code(current_criteria, language="text")
            else:
                st.sidebar.info("설정된 특화 기준이 없습니다.")
            
            # 편집 영역
            new_duplicate_criteria = st.sidebar.text_area(
                "그룹핑 특화 기준 편집",
                value=current_criteria,
                help="이 회사에만 적용될 추가 그룹핑 기준을 입력하세요.",
                key=f"edit_duplicate_{company_to_manage}",
                height=150
            )
            
            # 업데이트 함수
            def update_duplicate_criteria():
                st.session_state.company_additional_duplicate_handling[company_to_manage] = new_duplicate_criteria
                st.sidebar.success(f"'{company_to_manage}'의 그룹핑 특화 기준이 업데이트되었습니다!")
            
            # 업데이트 버튼
            if st.sidebar.button("그룹핑 기준 업데이트", key=f"update_duplicate_{company_to_manage}", on_click=update_duplicate_criteria):
                pass
                
        elif criteria_tabs == "3단계: 선택 기준":
            current_criteria = st.session_state.company_additional_selection_criteria.get(company_to_manage, "")
            st.sidebar.markdown(f"**현재 '{company_to_manage}'의 선택 특화 기준:**")
            if current_criteria.strip():
                st.sidebar.code(current_criteria, language="text")
            else:
                st.sidebar.info("설정된 특화 기준이 없습니다.")
            
            # 편집 영역
            new_selection_criteria = st.sidebar.text_area(
                "선택 특화 기준 편집",
                value=current_criteria,
                help="이 회사에만 적용될 추가 선택 기준을 입력하세요.",
                key=f"edit_selection_{company_to_manage}",
                height=150
            )
            
            # 업데이트 함수
            def update_selection_criteria():
                st.session_state.company_additional_selection_criteria[company_to_manage] = new_selection_criteria
                st.sidebar.success(f"'{company_to_manage}'의 선택 특화 기준이 업데이트되었습니다!")
            
            # 업데이트 버튼
            if st.sidebar.button("선택 기준 업데이트", key=f"update_selection_{company_to_manage}", on_click=update_selection_criteria):
                pass

# 미리보기 버튼 - 모든 회사별 특화 기준 확인
with st.sidebar.expander("🔍 전체 회사별 특화 기준 미리보기"):
    if selected_companies:
        # 세션 상태가 초기화되지 않은 경우를 위한 안전장치
        if 'company_additional_exclusion_criteria' not in st.session_state:
            st.session_state.company_additional_exclusion_criteria = COMPANY_ADDITIONAL_EXCLUSION_CRITERIA.copy()
        if 'company_additional_duplicate_handling' not in st.session_state:
            st.session_state.company_additional_duplicate_handling = COMPANY_ADDITIONAL_DUPLICATE_HANDLING.copy()
        if 'company_additional_selection_criteria' not in st.session_state:
            st.session_state.company_additional_selection_criteria = COMPANY_ADDITIONAL_SELECTION_CRITERIA.copy()
            
        for i, company in enumerate(selected_companies, 1):
            st.markdown(f"**{i}. {company}**")
            
            # 1단계 제외 기준 (세션 상태에서 가져오기)
            exclusion_criteria_text = st.session_state.company_additional_exclusion_criteria.get(company, "")
            if exclusion_criteria_text.strip():
                st.markdown("📝 **제외 특화 기준:**")
                st.text(exclusion_criteria_text[:100] + "..." if len(exclusion_criteria_text) > 100 else exclusion_criteria_text)
            
            # 2단계 그룹핑 기준 (세션 상태에서 가져오기)
            duplicate_criteria_text = st.session_state.company_additional_duplicate_handling.get(company, "")
            if duplicate_criteria_text.strip():
                st.markdown("🔄 **그룹핑 특화 기준:**")
                st.text(duplicate_criteria_text[:100] + "..." if len(duplicate_criteria_text) > 100 else duplicate_criteria_text)
            
            # 3단계 선택 기준 (세션 상태에서 가져오기)
            selection_criteria_text = st.session_state.company_additional_selection_criteria.get(company, "")
            if selection_criteria_text.strip():
                st.markdown("✅ **선택 특화 기준:**")
                st.text(selection_criteria_text[:100] + "..." if len(selection_criteria_text) > 100 else selection_criteria_text)
            
            if not (exclusion_criteria_text.strip() or duplicate_criteria_text.strip() or selection_criteria_text.strip()):
                st.info("설정된 특화 기준이 없습니다.")
            
            st.markdown("---")
    else:
        st.info("기업을 먼저 선택해주세요.")

# 구분선 추가
st.sidebar.markdown("---")

# GPT 모델 선택 섹션
st.sidebar.markdown("### 🤖 GPT 모델 선택")

selected_model = st.sidebar.selectbox(
    "분석에 사용할 GPT 모델을 선택하세요",
    options=list(GPT_MODELS.keys()),
    index=list(GPT_MODELS.keys()).index(DEFAULT_GPT_MODEL) if DEFAULT_GPT_MODEL in GPT_MODELS else 0,
    format_func=lambda x: f"{x} - {GPT_MODELS[x]}",
    help="각 모델의 특성:\n" + "\n".join([f"• {k}: {v}" for k, v in GPT_MODELS.items()])
)

# 모델 설명 표시
st.sidebar.markdown(f"""
<div style='background-color: #f0f2f6; padding: 10px; border-radius: 5px; margin-bottom: 20px;'>
    <strong>선택된 모델:</strong> {selected_model}<br>
    <strong>특징:</strong> {GPT_MODELS[selected_model]}
</div>
""", unsafe_allow_html=True)

# 구분선 추가
st.sidebar.markdown("---")

# 검색 결과 수 - 고정 값으로 설정
max_results = 100

# 시스템 프롬프트 설정
st.sidebar.markdown("### 🤖 시스템 프롬프트")

# 1단계: 제외 판단 시스템 프롬프트
system_prompt_1 = st.sidebar.text_area(
    "1단계: 제외 판단",
    value=SYSTEM_PROMPT_1,
    help="1단계 제외 판단에 사용되는 시스템 프롬프트를 설정하세요.",
    key="system_prompt_1",
    height=300
)

# 2단계: 그룹핑 시스템 프롬프트
system_prompt_2 = st.sidebar.text_area(
    "2단계: 그룹핑",
    value=SYSTEM_PROMPT_2,
    help="2단계 그룹핑에 사용되는 시스템 프롬프트를 설정하세요.",
    key="system_prompt_2",
    height=300
)

# 3단계: 중요도 평가 시스템 프롬프트 (템플릿)
system_prompt_3 = st.sidebar.text_area(
    "3단계: 중요도 평가 (템플릿)",
    value=SYSTEM_PROMPT_3_BASE,
    help="3단계 중요도 평가에 사용되는 시스템 프롬프트 템플릿을 설정하세요. 실제 분석 시 카테고리별 최대 기사 수가 자동으로 적용됩니다.",
    key="system_prompt_3",
    height=300
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📋 1단계: 제외 판단 기준")

# 제외 기준 설정 - 기본 기준만 표시하고 사용자 수정 허용
exclusion_criteria = st.sidebar.text_area(
    "❌ 제외 기준",
    value=EXCLUSION_CRITERIA,
    help="분석에서 제외할 뉴스의 기준을 설정하세요. 실제 분석 시 각 회사별 특화 기준이 추가로 적용됩니다.",
    key="exclusion_criteria",
    height=300
)


# 구분선 추가
st.sidebar.markdown("---")

# 2단계: 그룹핑 기준
st.sidebar.markdown("### 📋 2단계: 그룹핑 기준")

# 중복 처리 기준 설정 - 기본 기준만 표시하고 사용자 수정 허용
duplicate_handling = st.sidebar.text_area(
    "🔄 중복 처리 기준",
    value=DUPLICATE_HANDLING,
    help="중복된 뉴스를 처리하는 기준을 설정하세요. 실제 분석 시 각 회사별 특화 기준이 추가로 적용됩니다.",
    key="duplicate_handling",
    height=300
)

# 구분선 추가
st.sidebar.markdown("---")

# 3단계: 선택 기준
st.sidebar.markdown("### 📋 3단계: 선택 기준")

# 선택 기준 설정 - 기본 기준만 표시하고 사용자 수정 허용
selection_criteria = st.sidebar.text_area(
    "✅ 선택 기준",
    value=SELECTION_CRITERIA,
    help="뉴스 선택에 적용할 주요 기준들을 나열하세요. 실제 분석 시 각 회사별 특화 기준이 추가로 적용됩니다.",
    key="selection_criteria",
    height=300
)

# 응답 형식 설정
response_format = st.sidebar.text_area(
    "📝 응답 형식",
    value="""선택된 뉴스 인덱스: [1, 3, 5]와 같은 형식으로 알려주세요.

각 선택된 뉴스에 대해:
제목: (뉴스 제목)
언론사: (언론사명)
발행일: (발행일자)
선정 사유: (구체적인 선정 이유)
분석 키워드: (해당 기업 그룹의 주요 계열사들)

[제외된 주요 뉴스]
제외된 중요 뉴스들에 대해:
인덱스: (뉴스 인덱스)
제목: (뉴스 제목)
제외 사유: (구체적인 제외 이유)""",
    help="분석 결과의 출력 형식을 설정하세요.",
    key="response_format",
    height=200
)

# 최종 프롬프트 생성
analysis_prompt = f"""
당신은 회계법인의 전문 애널리스트입니다. 아래 뉴스 목록을 분석하여 회계법인 관점에서 가장 중요한 뉴스를 선별하세요. 

[선택 기준]
{selection_criteria}

[제외 대상]
{exclusion_criteria}

[응답 요구사항]
1. 선택 기준에 부합하는 뉴스가 많다면 최대 3개까지 선택 가능합니다.
2. 선택 기준에 부합하는 뉴스가 없다면, 그 이유를 명확히 설명해주세요.

[응답 형식]
다음과 같은 JSON 형식으로 응답해주세요:

{{
    "selected_news": [
        {{
            "index": 1,
            "title": "뉴스 제목",
            "press": "언론사명",
            "date": "발행일자",
            "reason": "선정 사유",
            "keywords": ["키워드1", "키워드2"]
        }},
        ...
    ],
    "excluded_news": [
        {{
            "index": 2,
            "title": "뉴스 제목",
            "reason": "제외 사유"
        }},
        ...
    ]
}}

[유효 언론사]
{valid_press_dict}

[중복 처리 기준]
{duplicate_handling}
"""

# 메인 컨텐츠
if st.button("뉴스 분석 시작", type="primary"):
    # 이메일 미리보기를 위한 전체 내용 저장
    email_content = "[Client Intelligence]\n\n"
    
    # 모든 키워드 분석 결과를 저장할 딕셔너리
    all_results = {}
    
    for i, company in enumerate(selected_companies, 1):
        with st.spinner(f"'{company}' 관련 뉴스를 수집하고 분석 중입니다..."):
            # 해당 회사의 연관 키워드 확장 (세션 상태에서 가져옴)
            company_keywords = st.session_state.company_keyword_map.get(company, [company])
            
            # 연관 키워드 표시
            st.write(f"'{company}' 연관 키워드로 검색 중: {', '.join(company_keywords)}")
            
            # 1. 회사의 카테고리 판단
            company_category = get_company_category(company)
            st.write(f"[{company}] 카테고리: {company_category}")
            
            # 2. 회사별 최대 기사 수 확인 (우선적으로 회사별 설정 사용)
            max_articles = get_max_articles_for_company(company)
            if max_articles == NO_LIMIT:
                st.write(f"[{company}] 최대 기사 수: 제한 없음 (중요도에 따라 모든 기사 선정 가능)")
            else:
                st.write(f"[{company}] 최대 기사 수: {max_articles}개")
            
            # 3. 회사별 시스템 프롬프트 생성 (사용자 수정 템플릿 사용)
            # 사용자가 수정한 템플릿에 회사별 최대 기사 수 적용
            try:
                if max_articles == NO_LIMIT:
                    # "제한 없음"인 경우 포맷팅 없이 기본 함수 사용
                    dynamic_system_prompt_3 = get_system_prompt_3(company)
                else:
                    dynamic_system_prompt_3 = system_prompt_3.format(max_articles=max_articles)
            except:
                # 포맷팅 실패 시 기본 함수 사용
                dynamic_system_prompt_3 = get_system_prompt_3(company)
            
            # 사용자가 수정한 기준을 기본으로 하고, 해당 회사의 추가 특화 기준만 더함
            base_exclusion = exclusion_criteria
            base_duplicate = duplicate_handling
            base_selection = selection_criteria
            
            # 해당 회사의 추가 특화 기준만 가져오기 (세션 상태에서)
            # 세션 상태가 초기화되지 않은 경우를 위한 안전장치
            if 'company_additional_exclusion_criteria' not in st.session_state:
                st.session_state.company_additional_exclusion_criteria = COMPANY_ADDITIONAL_EXCLUSION_CRITERIA.copy()
            if 'company_additional_duplicate_handling' not in st.session_state:
                st.session_state.company_additional_duplicate_handling = COMPANY_ADDITIONAL_DUPLICATE_HANDLING.copy()
            if 'company_additional_selection_criteria' not in st.session_state:
                st.session_state.company_additional_selection_criteria = COMPANY_ADDITIONAL_SELECTION_CRITERIA.copy()
                
            company_additional_exclusion = st.session_state.company_additional_exclusion_criteria.get(company, "")
            company_additional_duplicate = st.session_state.company_additional_duplicate_handling.get(company, "")
            company_additional_selection = st.session_state.company_additional_selection_criteria.get(company, "")
            
            # 사용자 수정 기준에 키워드 정보를 동적으로 치환하고 회사 특화 기준 결합
            enhanced_exclusion_criteria = get_enhanced_exclusion_criteria([company], base_exclusion)
            enhanced_duplicate_handling = get_enhanced_duplicate_handling([company], base_duplicate)
            enhanced_selection_criteria = get_enhanced_selection_criteria([company], base_selection)
            
            # initial_state 설정 부분 직전에 valid_press_dict를 딕셔너리로 변환하는 코드 추가
            # 텍스트 에어리어의 내용을 딕셔너리로 변환
            valid_press_config = {}
            try:
                # 문자열에서 딕셔너리 파싱
                lines = valid_press_dict.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line and ': ' in line:
                        press_name, aliases_str = line.split(':', 1)
                        try:
                            # 문자열 형태의 리스트를 실제 리스트로 변환
                            aliases = eval(aliases_str.strip())
                            valid_press_config[press_name.strip()] = aliases
                            print(f"[DEBUG] Valid press 파싱 성공: {press_name.strip()} -> {aliases}")
                        except Exception as e:
                            print(f"[DEBUG] Valid press 파싱 실패: {line}, 오류: {str(e)}")
            except Exception as e:
                print(f"[DEBUG] Valid press 전체 파싱 실패: {str(e)}")
                # 오류 발생 시 빈 딕셔너리 사용
                valid_press_config = {}
            
            print(f"[DEBUG] 파싱된 valid_press_dict: {valid_press_config}")
            
            # 추가 언론사도 파싱
            additional_press_config = {}
            try:
                # 문자열에서 딕셔너리 파싱
                lines = additional_press_dict.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if line and ': ' in line:
                        press_name, aliases_str = line.split(':', 1)
                        try:
                            # 문자열 형태의 리스트를 실제 리스트로 변환
                            aliases = eval(aliases_str.strip())
                            additional_press_config[press_name.strip()] = aliases
                            print(f"[DEBUG] Additional press 파싱 성공: {press_name.strip()} -> {aliases}")
                        except Exception as e:
                            print(f"[DEBUG] Additional press 파싱 실패: {line}, 오류: {str(e)}")
            except Exception as e:
                print(f"[DEBUG] Additional press 전체 파싱 실패: {str(e)}")
                # 오류 발생 시 빈 딕셔너리 사용
                additional_press_config = {}
            
            print(f"[DEBUG] 파싱된 additional_press_dict: {additional_press_config}")
            
            # 카테고리별 제외 언론사 별칭 가져오기 (Financial 전용 등)
            main_category = get_main_category_for_company(company)
            excluded_press_aliases = get_excluded_press_aliases_for_category(main_category)

            # 각 키워드별 상태 초기화
            initial_state = {
                "news_data": [], 
                "filtered_news": [], 
                "analysis": "", 
                "keyword": company_keywords,  # 회사별 확장 키워드 리스트 전달
                "model": selected_model,
                "excluded_news": [],
                "borderline_news": [],
                "retained_news": [],
                "grouped_news": [],
                "final_selection": [],
                # 회사별 enhanced 기준들 적용
                "exclusion_criteria": enhanced_exclusion_criteria,
                "duplicate_handling": enhanced_duplicate_handling,
                "selection_criteria": enhanced_selection_criteria,
                "system_prompt_1": system_prompt_1,
                "user_prompt_1": "",
                "llm_response_1": "",
                "system_prompt_2": system_prompt_2,
                "user_prompt_2": "",
                "llm_response_2": "",
                "system_prompt_3": dynamic_system_prompt_3,
                "user_prompt_3": "",
                "llm_response_3": "",
                "not_selected_news": [],
                "original_news_data": [],
                # 언론사 설정 추가 (파싱된 딕셔너리 사용)
                "valid_press_dict": valid_press_config,
                # 추가 언론사 설정 추가
                "additional_press_dict": additional_press_config,
                # Rule 기반 키워드 필터링 목록 추가 (사용자 입력 값 사용)
                "excluded_keywords": excluded_keywords_list,
                # 카테고리별 제외 언론사 별칭 추가 (Financial에서 딜사이트플러스, 딜사이트TV플러스 제외)
                "excluded_press_aliases": excluded_press_aliases,
                # 날짜 필터 정보 추가
                "start_datetime": datetime.combine(start_date, start_time, KST),
                "end_datetime": datetime.combine(end_date, end_time, KST)
                #"start_datetime": start_datetime,
                #"end_datetime": end_datetime
            }
            
            
            print(f"[DEBUG] start_datetime: {datetime.combine(start_date, start_time)}")
            print(f"[DEBUG] end_datetime: {datetime.combine(end_date, end_time)}")
            
            # 1단계: 뉴스 수집
            st.write("1단계: 뉴스 수집 중...")
            state_after_collection = collect_news(initial_state)
            
            # 2단계: 유효 언론사 필터링
            st.write("2단계: 유효 언론사 필터링 중...")
            state_after_press_filter = filter_valid_press(state_after_collection)
            
            # 2.5단계: Rule 기반 키워드 필터링
            st.write("2.5단계: Rule 기반 키워드 필터링 중...")
            state_after_keyword_filter = filter_excluded_keywords(state_after_press_filter)
            
            # 3단계: 제외 판단
            st.write("3단계: 제외 판단 중...")
            state_after_exclusion = filter_excluded_news(state_after_keyword_filter)
            
            # 4단계: 그룹핑
            st.write("4단계: 그룹핑 중...")
            state_after_grouping = group_and_select_news(state_after_exclusion)
            
            # 5단계: 중요도 평가
            st.write("5단계: 중요도 평가 중...")
            final_state = evaluate_importance(state_after_grouping)

            # 6단계: 0개 선택 시 완화된 기준으로 처음부터 재평가
            if len(final_state["final_selection"]) == 0:
                # Financial 카테고리는 재평가를 수행하지 않음
                if company_category == "금융지주" or company_category == "비지주금융그룹" or company_category == "핀테크":
                    st.write(f"6단계: [{company}] Financial 카테고리는 재평가를 수행하지 않습니다. (카테고리: {company_category})")
                else:
                    st.write("6단계: 선택된 뉴스가 없어 완화된 기준으로 처음부터 재평가를 시작합니다...")
                    
                    # 추가 언론사를 포함한 확장된 언론사 설정
                    expanded_valid_press_dict = {**valid_press_config, **additional_press_config}
                    
                    # 회사별 키워드 정보를 완화된 기준에도 동적으로 추가
                    company_keywords = COMPANY_KEYWORD_MAP.get(company, [company])
                    company_keywords_info = f"\n\n[분석 대상 기업별 키워드 목록]\n• {company}: {', '.join(company_keywords)}\n"
                    
                    # 완화된 제외 기준에 키워드 정보를 동적으로 치환
                    updated_relaxed_exclusion = RELAXED_EXCLUSION_CRITERIA.replace(
                        "- 각 회사별 키워드 목록은 COMPANY_KEYWORD_MAP 참조",
                        f"- 해당 기업의 키워드: {company_keywords_info.strip()}"
                    )
                    
                    # 회사별 완화된 특화 기준 생성
                    relaxed_exclusion_criteria = updated_relaxed_exclusion + company_additional_exclusion
                    relaxed_duplicate_handling = RELAXED_DUPLICATE_HANDLING + company_additional_duplicate
                    relaxed_selection_criteria = RELAXED_SELECTION_CRITERIA + company_additional_selection
                    
                    # 완화된 기준으로 새로운 초기 상태 생성 (기존 수집된 뉴스 재사용)
                    relaxed_initial_state = {
                        "news_data": final_state.get("original_news_data", []),  # 기존 수집된 뉴스를 news_data로 복사
                        "filtered_news": [], 
                        "analysis": "", 
                        "keyword": company_keywords,
                        "model": selected_model,
                        "excluded_news": [],
                        "borderline_news": [],
                        "retained_news": [],
                        "grouped_news": [],
                        "final_selection": [],
                        # 완화된 기준들 적용
                        "exclusion_criteria": relaxed_exclusion_criteria,
                        "duplicate_handling": relaxed_duplicate_handling,
                        "selection_criteria": relaxed_selection_criteria,
                        "system_prompt_1": system_prompt_1,
                        "user_prompt_1": "",
                        "llm_response_1": "",
                        "system_prompt_2": system_prompt_2,
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
                        # Rule 기반 키워드 필터링 목록 추가 (사용자 입력 값 사용)
                        "excluded_keywords": excluded_keywords_list,
                        # 날짜 필터 정보
                        "start_datetime": datetime.combine(start_date, start_time, KST),
                        "end_datetime": datetime.combine(end_date, end_time, KST)
                    }
                    
                    st.write("- 1단계: 기존 수집된 뉴스 재사용 (재평가)")
                    # 뉴스 수집 단계 건너뛰고 기존 데이터 사용
                    relaxed_state_after_collection = relaxed_initial_state
                    
                    st.write("- 2단계: 확장된 언론사 필터링 (재평가) 중...")
                    relaxed_state_after_press_filter = filter_valid_press(relaxed_state_after_collection)
                    
                    st.write("- 2.5단계: Rule 기반 키워드 필터링 (재평가) 중...")
                    relaxed_state_after_keyword_filter = filter_excluded_keywords(relaxed_state_after_press_filter)
                    
                    st.write("- 3단계: 완화된 제외 판단 (재평가) 중...")
                    relaxed_state_after_exclusion = filter_excluded_news(relaxed_state_after_keyword_filter)
                    
                    st.write("- 4단계: 완화된 그룹핑 (재평가) 중...")
                    relaxed_state_after_grouping = group_and_select_news(relaxed_state_after_exclusion)
                    
                    st.write("- 5단계: 완화된 중요도 평가 (재평가) 중...")
                    relaxed_final_state = evaluate_importance(relaxed_state_after_grouping)
                    
                    # 재평가 결과가 있으면 최종 상태 업데이트
                    if "final_selection" in relaxed_final_state and relaxed_final_state["final_selection"]:
                        final_state.update(relaxed_final_state)
                        final_state["is_reevaluated"] = True
                        st.success(f"완화된 기준으로 재평가 후 {len(final_state['final_selection'])}개의 뉴스가 선택되었습니다.")
                        
                        # 재평가 상태 정보를 디버그용으로 저장
                        final_state["reevaluation_debug"] = {
                            "relaxed_exclusion_criteria": relaxed_exclusion_criteria,
                            "relaxed_duplicate_handling": relaxed_duplicate_handling,
                            "relaxed_selection_criteria": relaxed_selection_criteria,
                            "expanded_press_count": len(expanded_valid_press_dict),
                            "news_after_collection": len(final_state.get("original_news_data", [])),  # 기존 수집된 뉴스 수
                            "news_after_press_filter": len(relaxed_state_after_press_filter.get("news_data", [])),
                            "news_after_exclusion": len(relaxed_state_after_exclusion.get("retained_news", [])),
                            "news_after_grouping": len(relaxed_state_after_grouping.get("grouped_news", []))
                        }
                    else:
                        st.error("완화된 기준으로 재평가 후에도 선정할 수 있는 뉴스가 없습니다.")

            # 키워드별 분석 결과 저장
            all_results[company] = final_state["final_selection"]
            
            # 키워드 구분선 추가
            st.markdown("---")
            
            # 키워드별 섹션 구분
            st.markdown(f"## 📊 {company} 분석 결과")
            
            # 전체 뉴스 표시 (필터링 전)
            with st.expander(f"📰 '{company}' 관련 전체 뉴스 (필터링 전)"):
                for i, news in enumerate(final_state.get("original_news_data", []), 1):
                    date_str = news.get('date', '날짜 정보 없음')
                    url = news.get('url', 'URL 정보 없음')
                    press = news.get('press', '알 수 없음')
                    st.markdown(f"""
                    <div class="news-card">
                        <div class="news-title">{i}. {news['content']}</div>
                        <div class="news-meta">📰 {press}</div>
                        <div class="news-date">📅 {date_str}</div>
                        <div class="news-url">🔗 <a href="{url}" target="_blank">{url}</a></div>
                    </div>
                    """, unsafe_allow_html=True)
            
            # 유효 언론사 필터링된 뉴스 표시
            with st.expander(f"📰 '{company}' 관련 유효 언론사 뉴스"):
                for i, news in enumerate(final_state["news_data"]):
                    date_str = news.get('date', '날짜 정보 없음')
                    url = news.get('url', 'URL 정보 없음')
                    press = news.get('press', '알 수 없음')
                    st.markdown(f"""
                    <div class="news-card">
                        <div class="news-title">{i+1}. {news['content']}</div>
                        <div class="news-meta">📰 {press}</div>
                        <div class="news-date">📅 {date_str}</div>
                        <div class="news-url">🔗 <a href="{url}" target="_blank">{url}</a></div>
                    </div>
                    """, unsafe_allow_html=True)
            
            # 2단계: 유효 언론사 필터링 결과 표시
            st.markdown("<div class='subtitle'>🔍 2단계: 유효 언론사 필터링 결과</div>", unsafe_allow_html=True)
            st.markdown(f"유효 언론사 뉴스: {len(final_state['news_data'])}개")
            
            # 3단계: 제외/보류/유지 뉴스 표시
            st.markdown("<div class='subtitle'>🔍 3단계: 뉴스 분류 결과</div>", unsafe_allow_html=True)
            
            # 제외된 뉴스
            with st.expander("❌ 제외된 뉴스"):
                for news in final_state["excluded_news"]:
                    st.markdown(f"<div class='excluded-news'>[{news['index']}] {news['title']}<br/>└ {news['reason']}</div>", unsafe_allow_html=True)
            
            # 보류 뉴스
            with st.expander("⚠️ 보류 뉴스"):
                for news in final_state["borderline_news"]:
                    st.markdown(f"<div class='excluded-news'>[{news['index']}] {news['title']}<br/>└ {news['reason']}</div>", unsafe_allow_html=True)
            
            # 유지 뉴스
            with st.expander("✅ 유지 뉴스"):
                for news in final_state["retained_news"]:
                    st.markdown(f"<div class='excluded-news'>[{news['index']}] {news['title']}<br/>└ {news['reason']}</div>", unsafe_allow_html=True)
            
            # 4단계: 그룹핑 결과 표시
            st.markdown("<div class='subtitle'>🔍 4단계: 뉴스 그룹핑 결과</div>", unsafe_allow_html=True)
            
            with st.expander("📋 그룹핑 결과 보기"):
                for group in final_state["grouped_news"]:
                    st.markdown(f"""
                    <div class="analysis-section">
                        <h4>그룹 {group['indices']}</h4>
                        <p>선택된 기사: {group['selected_index']}</p>
                        <p>선정 이유: {group['reason']}</p>
                    </div>
                    """, unsafe_allow_html=True)
            
            # 5단계: 최종 선택 결과 표시
            st.markdown("<div class='subtitle'>🔍 5단계: 최종 선택 결과</div>", unsafe_allow_html=True)
            
            # 재평가 여부 확인 (is_reevaluated 필드 있으면 재평가된 것)
            was_reevaluated = final_state.get("is_reevaluated", False)
            
            # 재평가 여부에 따라 메시지와 스타일 변경
            if was_reevaluated:
                # 재평가가 수행된 경우 6단계 표시
                st.warning("5단계에서 선정된 뉴스가 없어 6단계 재평가를 진행했습니다.")
                st.markdown("<div class='subtitle'>🔍 6단계: 재평가 결과</div>", unsafe_allow_html=True)
                st.markdown("### 📰 재평가 후 선정된 뉴스")
                # 재평가 스타일 적용
                news_style = "border-left: 4px solid #FFA500; background-color: #FFF8DC;"
                reason_prefix = "<span style=\"color: #FFA500; font-weight: bold;\">재평가 후</span> 선별 이유: "
            else:
                # 정상적으로 5단계에서 선정된 경우
                st.markdown("### 📰 최종 선정된 뉴스")  
                # 일반 스타일 적용
                news_style = ""
                reason_prefix = "선별 이유: "
            
            # 최종 선정된 뉴스 표시
            for news in final_state["final_selection"]:
                # 날짜 형식 변환
                
                date_str = format_date(news.get('date', ''))
                
                try:
                    # YYYY-MM-DD 형식으로 가정
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    formatted_date = date_obj.strftime('%m/%d')
                except Exception as e:
                    try:
                        # GMT 형식 시도
                        date_obj = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %Z')
                        formatted_date = date_obj.strftime('%m/%d')
                    except Exception as e:
                        formatted_date = date_str if date_str else '날짜 정보 없음'

                url = news.get('url', 'URL 정보 없음')
                press = news.get('press', '언론사 정보 없음')
                
                # 뉴스 정보 표시
                st.markdown(f"""
                    <div class="selected-news" style="{news_style}">
                        <div class="news-title-large">{news['title']} ({formatted_date})</div>
                        <div class="news-url">🔗 <a href="{url}" target="_blank">{url}</a></div>
                        <div class="selection-reason">
                            • {reason_prefix}{news['reason']}
                        </div>
                        <div class="news-summary">
                            • 키워드: {', '.join(news['keywords'])} | 관련 계열사: {', '.join(news['affiliates'])} | 언론사: {press}
                        </div>
                    </div>
                """, unsafe_allow_html=True)
                
                # 구분선 추가
                st.markdown("---")
            
            # 선정되지 않은 뉴스 표시
            if final_state.get("not_selected_news"):
                with st.expander("❌ 선정되지 않은 뉴스"):
                    for news in final_state["not_selected_news"]:
                        st.markdown(f"""
                        <div class="not-selected-news">
                            <div class="news-title">{news['index']}. {news['title']}</div>
                            <div class="importance-low">💡 중요도: {news['importance']}</div>
                            <div class="not-selected-reason">❌ 미선정 사유: {news['reason']}</div>
                        </div>
                        """, unsafe_allow_html=True)
            
            # 디버그 정보
            with st.expander("디버그 정보"):
                st.markdown("### 1단계: 제외 판단")
                st.markdown("#### 시스템 프롬프트")
                st.text(final_state.get("system_prompt_1", "없음"))
                st.markdown("#### 사용자 프롬프트")
                st.text(final_state.get("user_prompt_1", "없음"))
                st.markdown("#### LLM 응답")
                st.text(final_state.get("llm_response_1", "없음"))
                
                st.markdown("### 2단계: 그룹핑")
                st.markdown("#### 시스템 프롬프트")
                st.text(final_state.get("system_prompt_2", "없음"))
                st.markdown("#### 사용자 프롬프트")
                st.text(final_state.get("user_prompt_2", "없음"))
                st.markdown("#### LLM 응답")
                st.text(final_state.get("llm_response_2", "없음"))
                
                st.markdown("### 3단계: 중요도 평가")
                st.markdown("#### 시스템 프롬프트")
                st.text(final_state.get("system_prompt_3", "없음"))
                st.markdown("#### 사용자 프롬프트")
                st.text(final_state.get("user_prompt_3", "없음"))
                st.markdown("#### LLM 응답")
                st.text(final_state.get("llm_response_3", "없음"))
                
                # 6단계: 재평가 정보 추가
                if final_state.get("is_reevaluated", False):
                    st.markdown("### 6단계: 재평가 정보")
                    
                    # 재평가 디버그 정보 표시
                    if "reevaluation_debug" in final_state:
                        debug_info = final_state["reevaluation_debug"]
                        st.markdown("#### 재평가 통계")
                        st.text(f"확장된 언론사 수: {debug_info.get('expanded_press_count', 0)}개")
                        st.text(f"수집된 뉴스: {debug_info.get('news_after_collection', 0)}개")
                        st.text(f"언론사 필터링 후: {debug_info.get('news_after_press_filter', 0)}개")
                        st.text(f"제외 판단 후 유지: {debug_info.get('news_after_exclusion', 0)}개")
                        st.text(f"그룹핑 후: {debug_info.get('news_after_grouping', 0)}개")
                    
                    st.markdown("#### 재평가 시스템 프롬프트")
                    st.text(final_state.get("system_prompt_1", "제외 판단 프롬프트 정보 없음"))
                    st.text(final_state.get("system_prompt_2", "그룹핑 프롬프트 정보 없음"))
                    st.text(final_state.get("system_prompt_3", "중요도 평가 프롬프트 정보 없음"))
                    
                    st.markdown("#### 재평가 사용된 완화 기준")
                    if "reevaluation_debug" in final_state:
                        debug_info = final_state["reevaluation_debug"]
                        st.text("완화된 제외 기준:")
                        st.text(debug_info.get("relaxed_exclusion_criteria", "정보 없음")[:500] + "...")
                        st.text("완화된 그룹핑 기준:")
                        st.text(debug_info.get("relaxed_duplicate_handling", "정보 없음")[:500] + "...")
                        st.text("완화된 선택 기준:")
                        st.text(debug_info.get("relaxed_selection_criteria", "정보 없음")[:500] + "...")
            
            # 이메일 내용 추가
            email_content += f"{i}. {company}\n"
            for news in final_state["final_selection"]:
                # 날짜 형식 변환
                date_str = news.get('date', '')
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    formatted_date = date_obj.strftime('%m/%d')
                except Exception as e:
                    try:
                        date_obj = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %Z')
                        formatted_date = date_obj.strftime('%m/%d')
                    except Exception as e:
                        formatted_date = date_str if date_str else '날짜 정보 없음'
                
                url = news.get('url', '')
                email_content += f"  - {news['title']} ({formatted_date}) {url}\n"
            email_content += "\n"
            
            # 키워드 구분선 추가
            st.markdown("---")

    # 모든 키워드 분석이 끝난 후 이메일 미리보기 섹션 추가
    st.markdown("<div class='subtitle'>📧 이메일 미리보기</div>", unsafe_allow_html=True)
    
    # 카테고리 정보 가져오기 - 카테고리 모드에 따라 설정
    if category_mode == "개별 카테고리":
        # 개별 카테고리 모드: 하위 카테고리를 상위 카테고리로 매핑
        current_category = None
        if selected_subcategory in ["Anchor", "Growth & Whitespace"]:
            current_category = "Corporate"
        elif selected_subcategory in ["금융지주", "비지주 금융그룹", "핀테크"]:
            current_category = "Financial"
    else:
        # 통합 카테고리 모드: 선택된 메인 카테고리 직접 사용
        current_category = selected_main_category
    
    # 새로운 PwC 스타일 HTML 생성
    html_email_content = create_pwc_html_email(all_results, selected_companies, current_category, category_mode, selected_main_category)
    
    # 이메일 미리보기 표시
    st.markdown(html_email_content, unsafe_allow_html=True)



else:
    # 초기 화면 설명 (주석 처리됨)
    """
    ### 👋 PwC 뉴스 분석기에 오신 것을 환영합니다!
    
    이 도구는 입력한 키워드에 대한 최신 뉴스를 자동으로 수집하고, 회계법인 관점에서 중요한 뉴스를 선별하여 분석해드립니다.
    
    #### 주요 기능:
    1. 최신 뉴스 자동 수집 (기본 100개)
    2. 신뢰할 수 있는 언론사 필터링
    3. 6단계 AI 기반 뉴스 분석 프로세스:
       - 1단계: 뉴스 수집 - 키워드 기반으로 최신 뉴스 데이터 수집
       - 2단계: 유효 언론사 필터링 - 신뢰할 수 있는 언론사 선별
       - 3단계: 제외/보류/유지 판단 - 회계법인 관점에서의 중요도 1차 분류
       - 4단계: 유사 뉴스 그룹핑 - 중복 기사 제거 및 대표 기사 선정
       - 5단계: 중요도 평가 및 최종 선정 - 회계법인 관점의 중요도 평가
       - 6단계: 필요시 재평가 - 선정된 뉴스가 없을 경우 AI가 기준을 완화하여 재평가
    4. 선별된 뉴스에 대한 상세 정보 제공
       - 제목 및 날짜
       - 원문 링크
       - 선별 이유
       - 키워드, 관련 계열사, 언론사 정보
    5. 분석 결과 이메일 형식 미리보기
    
    #### 사용 방법:
    1. 사이드바에서 분석할 기업 카테고리와 기업을 선택하세요 (최대 10개)
       - **Anchor**: 삼성, SK, LG, 현대차, 롯데, 한화, 포스코
       - **Growth & Whitespace**: HD현대, 신세계, GS, LS, CJ  
       - **5대금융지주**: KB, 신한, 우리, 하나, NH
       - **인터넷뱅크**: 토스, 카카오, 케이뱅크
       - 새로운 기업 직접 추가 가능
    2. GPT 모델을 선택하세요
       - gpt-4.1: 최신모델 (기본값)
    3. 날짜 필터를 설정하세요
       - 기본값: 어제 또는 지난 금요일(월요일인 경우)부터 오늘까지
    4. "뉴스 분석 시작" 버튼을 클릭하세요
    
    #### 분석 결과 확인:
    - 각 기업별 최종 선정된 중요 뉴스
    - 선정 과정의 중간 결과(제외/보류/유지, 그룹핑 등)
    - 선정된 모든 뉴스의 요약 이메일 미리보기
    - 디버그 정보 (시스템 프롬프트, AI 응답 등)
    
    #### 새로운 카테고리 구조:
    - **세분화된 분석**: 4개 세부 카테고리로 정확한 타겟팅
    - **Anchor**: 대기업 핵심 그룹 (삼성, SK, LG, 현대차, 롯데, 한화, 포스코)
    - **Growth & Whitespace**: 성장 및 신규 타겟 기업 (HD현대, 신세계, GS, LS, CJ)
    - **5대금융지주**: 주요 금융지주 회사 (KB, 신한, 우리, 하나, NH)
    - **인터넷뱅크**: 디지털 금융 혁신 기업 (토스, 카카오, 케이뱅크)
    
    """

# 푸터
st.markdown("---")
st.markdown("© 2024 PwC 뉴스 분석기 | 회계법인 관점의 뉴스 분석 도구")
