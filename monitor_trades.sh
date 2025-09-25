#!/bin/bash

# Configuration
LOGPATH="/mnt/c/SuccessTrader Pro_x64/TradeSignal/Log"
SCRIPT_DIR="/home/rko/Dropbox_Projects/das2bookmap"
PROCESS_SCRIPT="$SCRIPT_DIR/process_symbols.py"
DELAYED_OUTPUT_SCRIPT="$SCRIPT_DIR/delayed_output.py"
VENV_PATH="/home/rko/venvs/trading"

# Default values
OUTPUT_DEST="/dev/pts/7"
OUTPUT_TYPE="tty"
TEST_MODE=false
TEST_CSV=""

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS] [CSV_FILE] [OUTPUT_DESTINATION]"
    echo ""
    echo "Options:"
    echo "  --tty     Output to TTY terminal (default)"
    echo "  --file    Output to file"
    echo "  --help    Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                                    # Normal mode, output to /dev/pts/7"
    echo "  $0 /dev/pts/5                        # Normal mode, output to /dev/pts/5"
    echo "  $0 --file output.log                 # Normal mode, output to file"
    echo "  $0 test.csv                          # Test mode, output to /dev/pts/7"
    echo "  $0 test.csv /dev/pts/5               # Test mode, output to /dev/pts/5"
    echo "  $0 --file test.csv output.log        # Test mode, output to file"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --tty)
            OUTPUT_TYPE="tty"
            shift
            ;;
        --file)
            OUTPUT_TYPE="file"
            shift
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *.csv)
            TEST_CSV="$1"
            TEST_MODE=true
            shift
            ;;
        *)
            OUTPUT_DEST="$1"
            shift
            ;;
    esac
done

# Set default output destination based on type if not specified
if [[ "$OUTPUT_DEST" == "/dev/pts/7" && "$OUTPUT_TYPE" == "file" ]]; then
    OUTPUT_DEST="trade_monitor_$(date +%Y%m%d_%H%M%S).log"
fi

# Get today's date in the format used by the log files
TODAY=$(date +%Y%m%d)

# Function to find today's logfile
find_todays_logfile() {
    # Look for files matching pattern: numbers_YYYYMMDD.csv
    find "$LOGPATH" -name "*_${TODAY}.csv" -type f 2>/dev/null | head -1
}

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

if [[ "$TEST_MODE" == true ]]; then
    log_message "TEST MODE: Using CSV file $TEST_CSV"
    log_message "Output type: $OUTPUT_TYPE"
    log_message "Output destination: $OUTPUT_DEST"
    
    # Check if test CSV exists
    if [[ ! -f "$TEST_CSV" ]]; then
        log_message "ERROR: Test CSV file $TEST_CSV does not exist"
        exit 1
    fi
    
    # Check output destination based on type
    if [[ "$OUTPUT_TYPE" == "tty" && ! -e "$OUTPUT_DEST" ]]; then
        log_message "ERROR: Terminal $OUTPUT_DEST does not exist"
        exit 1
    fi
    
    log_message "Starting test mode with delayed output..."
    source "$VENV_PATH/bin/activate"
    cat "$TEST_CSV" | python3 "$DELAYED_OUTPUT_SCRIPT" | python3 "$PROCESS_SCRIPT" --fetch-external > "$OUTPUT_DEST" 2>&1
    
else
    log_message "Starting trade monitor for date: $TODAY"
    log_message "Looking in path: $LOGPATH"
    log_message "Output type: $OUTPUT_TYPE"
    log_message "Output destination: $OUTPUT_DEST"

    # Check output destination based on type
    if [[ "$OUTPUT_TYPE" == "tty" && ! -e "$OUTPUT_DEST" ]]; then
        log_message "ERROR: Terminal $OUTPUT_DEST does not exist"
        exit 1
    fi

    # Main monitoring loop
    while true; do
        LOGFILE=$(find_todays_logfile)
        
        if [[ -n "$LOGFILE" ]]; then
            log_message "Found logfile: $LOGFILE"
            log_message "Starting tail -f and processing..."
            
            # Start tailing and processing the file, redirect output to destination
            source "$VENV_PATH/bin/activate"
            stdbuf -oL ./log_poller.sh "$LOGFILE" | tee /dev/pts/8 | python3 "$PROCESS_SCRIPT" --fetch-external > "$OUTPUT_DEST" 2>&1
            #stdbuf -oL tail -F -n +1 "$LOGFILE" | tee /dev/pts/8 | python3 "$PROCESS_SCRIPT" --fetch-external > "$OUTPUT_DEST" 2>&1
            
            # If we reach here, the process was interrupted
            log_message "Processing stopped"
            break
        else
            log_message "No logfile found for $TODAY, waiting 10 seconds..."
            sleep 10
        fi
    done
fi

log_message "Trade monitor exiting"
