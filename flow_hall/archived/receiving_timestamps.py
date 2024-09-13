# Add this code to the API to receive and process absolute timestamp ticklists

@flow_hall_router.post("/{from_node}/ticklist000")
async def ticklist000_received(from_node: str, data: Ticklist000):
    global last_recorded_frequency000
    received = pendulum.now('America/New_York').format('YYYY-MM-DD HH:mm:ss.SSS')
    print(f"[{received}]{from_node}: {len(data.TimestampNsList)} ticks received")
    if WRITE_CSV:
        # Save unprocessed
        file = directory + f"{from_node}_ticklist000.{now_for_file}.csv"
        with open(file, mode='a', newline='') as f:
            writer = csv.writer(f)
            for x in data.TimestampNsList:
                writer.writerow([x])
        # Save processed
        processed_times, processed_freqs = ticklist_processing.filter_and_record(data.TimestampNsList, 0, last_recorded_frequency000, timestamps=True)
        if processed_freqs:
            file = directory + f"{from_node}_frequency000.{now_for_file}.csv"
            with open(file, mode='a', newline='') as file:
                rows = zip(processed_times, processed_freqs)
                writer = csv.writer(file)
                writer.writerows(rows)
            last_recorded_frequency000 = processed_freqs[-1]
