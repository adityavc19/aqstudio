// Synthetic sample data. Always shown with a label saying it is made up; it runs through the
// real pipeline and the real AI, never a canned result.
export function sampleCsv() {
  const stations = [
    ["SAMPLE-A", "Sample Station A", 12.97, 77.55, 55],
    ["SAMPLE-B", "Sample Station B", 12.99, 77.6, 140],
    ["SAMPLE-C", "Sample Station C", 12.93, 77.58, 30],
  ];
  const rows = ["Station ID,Station Name,Latitude,Longitude,Timestamp,PM2.5 (ug/m3),PM10 (ug/m3),NO2 (mg/m3),SO2 (ug/m3)"];
  for (const [id, name, lat, lon, base] of stations) {
    for (let hour = 0; hour < 48; hour += 1) {
      const day = 13 + Math.floor(hour / 24);
      const hh = String(hour % 24).padStart(2, "0");
      const fault = id === "SAMPLE-B" && hour >= 4 && hour < 14;
      const rush = hour % 24 === 3 || hour % 24 === 15 ? 25 : 0;
      const pm25 = fault ? 500 : base + rush + ((hour * 7) % 23);
      const pm10 = id === "SAMPLE-C" && hour % 24 >= 18 && hour < 24 ? "" : base * 2 + rush + ((hour * 5) % 31);
      const no2 = ((18 + (hour % 9)) / 1000).toFixed(3);
      rows.push(`${id},${name},${lat},${lon},2026-11-${day}T${hh}:00:00Z,${pm25},${pm10},${no2},${8 + (hour % 5)}`);
    }
  }
  return rows.join("\n");
}
