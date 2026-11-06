VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


def viewer_url(rcept_no: str) -> str:
    return VIEWER_URL.format(rcept_no=rcept_no)
