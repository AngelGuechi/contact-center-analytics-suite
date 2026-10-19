"""Generate and import fictional intervals; never read operational source files."""
from datetime import datetime,timedelta,time
from io import BytesIO
from openpyxl import Workbook
from core import AHTStore,HEADERS

def main():
    store=AHTStore()
    if store.total_calls():
        print("The store already contains calls; use an empty demo data folder.")
        return
    today=datetime.now().date()
    for offset in range(4,-1,-1):
        day=today-timedelta(days=offset)
        for interval in range(4):
            start=datetime.combine(day,time(9))+timedelta(minutes=30*interval)
            end=start+timedelta(minutes=30)
            book=Workbook();sheet=book.active;sheet.title="Sheet1";sheet.append(HEADERS)
            for index in range(36):
                agent=index%12+1
                started=start+timedelta(seconds=20*index)
                talk=360+((agent*31+interval*17+offset*19)%260)
                hold=20+(index%5)*10;wrap=45+(index%4)*15
                sheet.append([f"DEMO-{day:%Y%m%d}-{interval:02}-{index:03}",f"A{agent:03}",
                    f"Demo Agent {agent:02}",f"Demo Supervisor {(agent-1)//4+1}","Demo Team","Demo Support",
                    started,started+timedelta(seconds=talk+hold+wrap),talk,hold,wrap,"Voice","Inbound"])
            data=BytesIO();book.save(data);book.close()
            name=f"Calls_{start:%Y-%m-%d_%H%M}_{end:%Y-%m-%d_%H%M}_r01.xlsx"
            store.import_bytes(data.getvalue(),name)
    print(f"Loaded {store.total_calls()} fictional calls.")

if __name__=="__main__":main()
