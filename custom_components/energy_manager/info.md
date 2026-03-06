# Energy Manager

ניהול אנרגיה סולארית בבית – קורא מצב סוללה, ייצור סולארי, צריכת בית, משתמש בתחזית (Open-Meteo + pvlib), מחשב אסטרטגיה ומפעיל/מכבה צרכנים אוטומטית.

## תכונות

- חיישנים: SOC סוללה, הספק סוללה, ייצור סולארי, צריכת בית
- תחזית סולארית (GHI/DNI/DHI מ-Open-Meteo, POA עם pvlib, תמיכה במספר סטרינגים)
- מנוע החלטות: מצבים saving / normal / wasting
- ניהול צרכנים (מתגים) עם השהיה ועדיפויות
- חיישנים: מצב, הספק זמין, תחזית נשארת, מצב רזרבה סוללה ועוד

## התקנה

הוסף ב-HACS: Custom repositories → `https://github.com/refael302/energy_management` → Integration, ואז התקן "Energy Manager".
