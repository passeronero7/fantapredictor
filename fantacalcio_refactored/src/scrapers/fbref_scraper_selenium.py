from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time

class FBRefSeleniumScraper:
    def __init__(self):
        options = Options()
        options.add_argument('--headless')  # Run in background
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
    
    def get_page(self, url):
        self.driver.get(url)
        time.sleep(3)  # Wait for page load
        return BeautifulSoup(self.driver.page_source, 'lxml')
    
    def close(self):
        self.driver.quit()
