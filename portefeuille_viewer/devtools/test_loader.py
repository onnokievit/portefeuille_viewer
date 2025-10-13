# portefeuille_viewer/devtools/test_loader.py
from portefeuille_viewer.data import repository

def test_load_open_opties():
    df = repository.load_open_opties()
    print(df.shape)
    print(df.columns)
    print(df.head())
    df = repository.load_open_opties()
    print(df.shape)
    print(df.columns)
    print(df.head())

if __name__ == "__main__":
    test_load_open_opties()



    
