CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS AnTrua_members (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS AnTrua_meals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  date DATE NOT NULL,
  dish_name TEXT NOT NULL,
  total_cost NUMERIC(12,2) NOT NULL,
  per_person_cost NUMERIC(12,2) NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS AnTrua_meal_participants (
  meal_id UUID REFERENCES AnTrua_meals(id) ON DELETE CASCADE,
  member_id UUID REFERENCES AnTrua_members(id) ON DELETE CASCADE,
  ate BOOLEAN DEFAULT FALSE,
  PRIMARY KEY (meal_id, member_id)
);

CREATE TABLE IF NOT EXISTS AnTrua_payments (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  member_id UUID REFERENCES AnTrua_members(id) ON DELETE CASCADE,
  meal_id UUID REFERENCES AnTrua_meals(id) ON DELETE CASCADE,
  amount NUMERIC(12,2) NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS AnTrua_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  member_name TEXT NOT NULL,
  action TEXT NOT NULL,
  details TEXT,
  amount NUMERIC(12,2),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meals_date ON AnTrua_meals(date);
CREATE INDEX IF NOT EXISTS idx_meals_dish_name ON AnTrua_meals(dish_name);
CREATE INDEX IF NOT EXISTS idx_payments_member_id ON AnTrua_payments(member_id);
CREATE INDEX IF NOT EXISTS idx_payments_meal_id ON AnTrua_payments(meal_id);
CREATE INDEX IF NOT EXISTS idx_logs_created_at ON AnTrua_logs(created_at DESC);