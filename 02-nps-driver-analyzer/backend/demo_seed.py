"""Create fictional input with no dependency on the original source attachment."""
from pathlib import Path
from datetime import datetime,timedelta
from openpyxl import Workbook

def main():
    destination=Path(__file__).resolve().parents[1]/"data"/"synthetic_call_detail.xlsx"
    if destination.exists():
        print("Synthetic sample already exists.");return
    destination.parent.mkdir(parents=True,exist_ok=True)
    book=Workbook();sheet=book.active
    sheet.append(["Transaction ID","Login ID","Agent Name","Start Date Time","Talk Time","Hold Time","Wrap Time","Transfer Flag","Skill"])
    index=0
    for day in range(15):
        for agent in range(1,43):
            for call in range(32):
                index+=1
                sheet.append([f"DEMO-TXN-{index:07}",f"U{200000+agent}",f"Demo Agent {agent:02}",
                    datetime(2026,8,3,8)+timedelta(days=day,minutes=call*20+agent%20),
                    300+(agent*17+call*23)%420,20+(agent+call)%70,30+call*3,
                    "Y" if call%5==0 else "N","EN" if agent%2 else "ES"])
    book.save(destination);book.close();print(f"Generated {index} fictional call rows.")

if __name__=="__main__":main()
