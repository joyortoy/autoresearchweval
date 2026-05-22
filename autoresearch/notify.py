def notify(enabled: bool, title:str, body:str=''):
    if enabled:
        print(f"[notify] {title}: {body}")
