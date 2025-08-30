// Board config for Wiznet W5500-EVB-Pico2 (RP2350 version)
#define MICROPY_HW_BOARD_NAME                   "W5500-EVB-Pico2"
#define MICROPY_HW_FLASH_STORAGE_BYTES          (PICO_FLASH_SIZE_BYTES - 1024 * 1024)

// Enable networking
#define MICROPY_PY_NETWORK_HOSTNAME_DEFAULT "W5500-EVB"

// Wiznet W5500-EVB-Pico2 default pins
#define MICROPY_HW_WIZNET_SPI_ID                (0)
#define MICROPY_HW_WIZNET_SPI_BAUDRATE          (20 * 1000 * 1000)
#define MICROPY_HW_WIZNET_SPI_SCK               (18)
#define MICROPY_HW_WIZNET_SPI_MOSI              (19)
#define MICROPY_HW_WIZNET_SPI_MISO              (16)
#define MICROPY_HW_WIZNET_PIN_CS                (17)
#define MICROPY_HW_WIZNET_PIN_RST               (20)
// Connecting the INTN pin enables RECV interrupt handling of incoming data
#define MICROPY_HW_WIZNET_PIN_INTN          (21)