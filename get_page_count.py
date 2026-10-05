"""Word COM으로 .docx의 실제 렌더링 페이지 수를 구한다 (단어수 추정이 아닌 정확한 값).
실행: python get_page_count.py <path.docx>
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
import os

import win32com.client


def page_count(path: str) -> int:
    path = os.path.abspath(path)
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = False
    try:
        doc = word.Documents.Open(path)
        try:
            return doc.ComputeStatistics(2)  # wdStatisticPages
        finally:
            doc.Close(False)
    finally:
        try:
            word.Quit()
        except Exception:
            pass


if __name__ == "__main__":
    print(page_count(sys.argv[1]))
