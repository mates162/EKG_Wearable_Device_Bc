#include <WiFi.h>        // Knihovna pro Wi-Fi připojení ESP32
#include <WiFiUdp.h>     // Knihovna pro UDP přenos

// ---------- KONFIGURACE ----------

// Piny na ESP32
#define LOplus 2
#define LOminus 1
#define output 0

// SSID a heslo k Wi-Fi síti
const char* SSID = "Pagi IOT";
const char* PASS = "mates3333";

// IP adresa počítače, kam se data posílají
const char* PC_IP = "192.168.50.202";    

// UDP port, který bude poslouchat Python skript
const uint16_t PC_PORT = 5005;          

// Počet vzorků v jednom datovém bloku
const uint16_t N = 1;                

// ---------- GLOBÁLNÍ PROMĚNNÉ ----------

WiFiUDP udp;            // Objekt pro UDP komunikaci
uint32_t seq = 0;       // Pořadové číslo bloku (sekvenční čítač)
int16_t buf[N];         // Pole, do kterého uložíme 100 náhodných vzorků

// Struktura hlavičky, která popisuje blok dat
// 'packed' zajistí, že kompilátor nepřidá žádné mezery mezi položky
struct __attribute__((packed)) Header {
  uint32_t seq;     // Pořadové číslo bloku (pro detekci ztrát)
  uint64_t t0_us;   // Čas v mikrosekundách, kdy byl blok začat
  uint16_t n;       // Počet vzorků v bloku
};

// ---------- FUNKCE SETUP ----------

void setup() {
  // Nastavení směrů pinů
  pinMode(LOplus, INPUT);
  pinMode(LOminus, INPUT);
  pinMode(output, INPUT);

  // Nastavení režimu Wi-Fi pouze jako stanice (bez AP)
  WiFi.mode(WIFI_STA);

  // Vypnutí uspávání, aby nedocházelo ke zpožděním při odesílání
  WiFi.setSleep(false);

  // Připojení k síti
  WiFi.begin(SSID, PASS);

  // Čekání, dokud se ESP32 nepřipojí k Wi-Fi
  while (WiFi.status() != WL_CONNECTED) {
    delay(200);  // Krátká pauza, aby se nezahltil sériový výstup
  }

  // (Volitelně) vypíšeme IP adresu do sériového monitoru
  Serial.begin(115200);
  Serial.print("Připojeno. IP adresa: ");
  Serial.println(WiFi.localIP());
}

// ---------- FUNKCE LOOP ----------

void loop() {
  // Uložíme si aktuální čas v mikrosekundách, kdy začínáme plnit blok
  const uint64_t t0 = esp_timer_get_time();

  // Naplníme pole buf náhodnými čísly (simulace měření)
  /*for (uint16_t i = 0; i < N; i++) {
    buf[i] = random(-32768, 32767);  // Náhodné int16 hodnoty
    delayMicroseconds(1000);         // Pauza 1 ms => efektivně 1 kHz
  }*/
  for (uint16_t i = 0; i < N; i++) {
    buf[i] = -analogRead(0);           // Data z AD8232
    delayMicroseconds(1000);         // Pauza 1 ms => efektivně 1 kHz
  }

  // Sestavíme hlavičku s metadaty bloku
  Header h;
  h.seq = seq++;     // Zvětšíme pořadové číslo bloku
  h.t0_us = t0;      // Čas, kdy blok začal
  h.n = N;           // Počet vzorků (10)

  // Začneme odesílat UDP paket na IP + port počítače
  udp.beginPacket(PC_IP, PC_PORT);

  // Nejprve pošleme hlavičku (velikost 14 bajtů)
  udp.write((uint8_t*)&h, sizeof(h));

  // Poté pošleme pole dat (100 × 2 bajty = 200 bajtů)
  udp.write((uint8_t*)buf, sizeof(buf));

  // Uzavřeme UDP paket (fyzicky odešle data)
  udp.endPacket();
  
  // Vypis stavu do serioveho monitoru
  Serial.print("Output: ");
  Serial.print(analogRead(output));
  Serial.print(", LOplus: ");
  Serial.print(digitalRead(LOplus));
  Serial.print(", LOminus: ");
  Serial.println(digitalRead(LOminus)); 

  // (Volitelně) malá pauza, aby přenos nezatěžoval síť
  delay(5);
}
