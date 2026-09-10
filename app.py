from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import psycopg2
import psycopg2.extras
import json
from datetime import datetime, date
from config import SUPABASE_URL, ADMIN_PASS, VIETQR

app = Flask(__name__)
app.secret_key = "an-trua-bsv-secret-key-2026"


def get_db():
    conn = psycopg2.connect(SUPABASE_URL)
    return conn


def get_member_id(name):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM AnTrua_members WHERE name = %s", (name,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


def ensure_member(name):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO AnTrua_members (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
    conn.commit()
    cur.close()
    conn.close()


@app.route("/api/members")
def api_AnTrua_members():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT
            m.name,
            COALESCE(
                (SELECT SUM(me.per_person_cost)
                 FROM AnTrua_meal_participants mp
                 JOIN AnTrua_meals me ON mp.meal_id = me.id
                 WHERE mp.member_id = m.id AND mp.ate = TRUE), 0
            ) - COALESCE(
                (SELECT SUM(p.amount)
                 FROM AnTrua_payments p
                 WHERE p.member_id = m.id), 0
            ) as debt
        FROM AnTrua_members m
        ORDER BY debt DESC
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    AnTrua_members = [{"name": row["name"], "debt": float(row["debt"])} for row in rows]
    return jsonify(AnTrua_members)


@app.route("/api/members/<name>/debt-details")
def api_member_debt_details(name):
    member_id = get_member_id(name)
    if not member_id:
        return jsonify({"error": "Member not found"}), 404

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT
            me.id as meal_id,
            me.dish_name as item_name,
            me.date,
            me.per_person_cost as amount
        FROM AnTrua_meal_participants mp
        JOIN AnTrua_meals me ON mp.meal_id = me.id
        WHERE mp.member_id = %s AND mp.ate = TRUE
        AND me.id NOT IN (
            SELECT meal_id FROM AnTrua_payments WHERE member_id = %s
        )
        ORDER BY me.date DESC
        """,
        (member_id, member_id),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    total_debt = sum(float(row["amount"]) for row in rows)
    unpaid_items = [
        {
            "mealId": str(row["meal_id"]),
            "itemName": row["item_name"],
            "date": row["date"].isoformat() if row["date"] else "",
            "amount": float(row["amount"]),
        }
        for row in rows
    ]

    return jsonify(
        {"memberName": name, "totalDebt": total_debt, "unpaidItems": unpaid_items}
    )


@app.route("/api/meals", methods=["POST"])
def api_add_meal():
    data = request.json
    date_str = data.get("date")
    dish_name = data.get("dishName", "").strip()
    total_cost = float(data.get("totalCost", 0))
    participants = data.get("participants", [])
    strangers = data.get("strangers", [])

    if not dish_name or total_cost <= 0 or not participants:
        return jsonify({"success": False, "message": "Thieu thong tin hoa don"}), 400

    all_participants = list(set(participants + strangers))
    per_person_cost = total_cost / len(all_participants)

    conn = get_db()
    cur = conn.cursor()

    try:
        for p in all_participants:
            ensure_member(p)

        meal_date = (
            datetime.strptime(date_str, "%Y-%m-%d").date()
            if isinstance(date_str, str)
            else date_str
        )
        cur.execute(
            "INSERT INTO AnTrua_meals (date, dish_name, total_cost, per_person_cost) VALUES (%s, %s, %s, %s) RETURNING id",
            (meal_date, dish_name, total_cost, per_person_cost),
        )
        meal_id = cur.fetchone()[0]

        for p in all_participants:
            mid = get_member_id(p)
            if mid:
                cur.execute(
                    "INSERT INTO AnTrua_meal_participants (meal_id, member_id, ate) VALUES (%s, %s, TRUE)",
                    (meal_id, mid),
                )

        cur.execute(
            "INSERT INTO AnTrua_logs (member_name, action, details, amount) VALUES (%s, %s, %s, %s)",
            ("System", "bill_added", f"Them hoa don: {dish_name} - {total_cost:.0f} VND", total_cost),
        )

        conn.commit()
        return jsonify({"success": True, "mealId": str(meal_id)})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/meals/<meal_id>", methods=["PUT"])
def api_edit_meal(meal_id):
    data = request.json
    dish_name = data.get("dishName", "").strip()
    total_cost = float(data.get("totalCost", 0))
    participants = data.get("participants", [])

    if not dish_name or total_cost <= 0 or not participants:
        return jsonify({"success": False, "message": "Thieu thong tin"}), 400

    per_person_cost = total_cost / len(participants)

    conn = get_db()
    cur = conn.cursor()

    try:
        for p in participants:
            ensure_member(p)

        cur.execute(
            "UPDATE AnTrua_meals SET dish_name = %s, total_cost = %s, per_person_cost = %s WHERE id = %s",
            (dish_name, total_cost, per_person_cost, meal_id),
        )

        cur.execute("DELETE FROM AnTrua_meal_participants WHERE meal_id = %s", (meal_id,))

        for p in participants:
            mid = get_member_id(p)
            if mid:
                cur.execute(
                    "INSERT INTO AnTrua_meal_participants (meal_id, member_id, ate) VALUES (%s, %s, TRUE)",
                    (meal_id, mid),
                )

        cur.execute(
            "INSERT INTO AnTrua_logs (member_name, action, details, amount) VALUES (%s, %s, %s, %s)",
            ("System", "bill_edited", f"Sua hoa don: {dish_name} - {total_cost:.0f} VND", total_cost),
        )

        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/meals/<meal_id>", methods=["DELETE"])
def api_delete_meal(meal_id):
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("SELECT dish_name, total_cost FROM AnTrua_meals WHERE id = %s", (meal_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "message": "Khong tim thay hoa don"}), 404

        cur.execute("DELETE FROM AnTrua_meals WHERE id = %s", (meal_id,))

        cur.execute(
            "INSERT INTO AnTrua_logs (member_name, action, details, amount) VALUES (%s, %s, %s, %s)",
            ("System", "bill_deleted", f"Xoa hoa don: {row[0]} - {row[1]:.0f} VND", row[1]),
        )

        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/meals")
def api_get_AnTrua_meals():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT m.id, m.date, m.dish_name, m.total_cost, m.per_person_cost, m.created_at
        FROM AnTrua_meals m
        ORDER BY m.date DESC, m.created_at DESC
        """
    )
    rows = cur.fetchall()

    AnTrua_meals = []
    for row in rows:
        cur2 = conn.cursor()
        cur2.execute(
            "SELECT mem.name FROM AnTrua_meal_participants mp JOIN AnTrua_members mem ON mp.member_id = mem.id WHERE mp.meal_id = %s AND mp.ate = TRUE",
            (row["id"],),
        )
        participants = [r[0] for r in cur2.fetchall()]
        cur2.close()

        AnTrua_meals.append(
            {
                "id": str(row["id"]),
                "date": row["date"].isoformat() if row["date"] else "",
                "dishName": row["dish_name"],
                "totalCost": float(row["total_cost"]),
                "perPersonCost": float(row["per_person_cost"]),
                "participants": participants,
                "createdAt": row["created_at"].isoformat() if row["created_at"] else "",
            }
        )

    cur.close()
    conn.close()
    return jsonify(AnTrua_meals)


@app.route("/api/meals/<meal_id>")
def api_get_meal(meal_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT id, date, dish_name, total_cost, per_person_cost FROM AnTrua_meals WHERE id = %s",
        (meal_id,),
    )
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return jsonify({"error": "Meal not found"}), 404

    cur2 = conn.cursor()
    cur2.execute(
        "SELECT mem.name FROM AnTrua_meal_participants mp JOIN AnTrua_members mem ON mp.member_id = mem.id WHERE mp.meal_id = %s AND mp.ate = TRUE",
        (meal_id,),
    )
    participants = [r[0] for r in cur2.fetchall()]
    cur2.close()
    cur.close()
    conn.close()

    return jsonify(
        {
            "id": str(row["id"]),
            "date": row["date"].isoformat() if row["date"] else "",
            "dishName": row["dish_name"],
            "totalCost": float(row["total_cost"]),
            "perPersonCost": float(row["per_person_cost"]),
            "participants": participants,
        }
    )


@app.route("/api/payments", methods=["POST"])
def api_record_payment():
    data = request.json
    member_name = data.get("memberName", "")
    meal_ids = data.get("mealIds", [])

    if not member_name or not meal_ids:
        return jsonify({"success": False, "message": "Thieu thong tin"}), 400

    member_id = get_member_id(member_name)
    if not member_id:
        return jsonify({"success": False, "message": "Khong tim thay thanh vien"}), 404

    conn = get_db()
    cur = conn.cursor()

    try:
        total_paid = 0
        for mid in meal_ids:
            cur.execute("SELECT per_person_cost FROM AnTrua_meals WHERE id = %s", (mid,))
            row = cur.fetchone()
            if row:
                amount = float(row[0])
                total_paid += amount
                cur.execute(
                    "INSERT INTO AnTrua_payments (member_id, meal_id, amount) VALUES (%s, %s, %s)",
                    (member_id, mid, amount),
                )

        cur.execute(
            "INSERT INTO AnTrua_logs (member_name, action, details, amount) VALUES (%s, %s, %s, %s)",
            (member_name, "payment", f"Thanh toan {len(meal_ids)} bua an", total_paid),
        )

        conn.commit()
        return jsonify({"success": True, "totalPaid": total_paid})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/payments/<payment_id>", methods=["DELETE"])
def api_revert_payment(payment_id):
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            "SELECT member_id, meal_id, amount FROM AnTrua_payments WHERE id = %s", (payment_id,)
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "message": "Khong tim thay khoan thanh toan"}), 404

        member_id, meal_id, amount = row

        cur.execute("SELECT name FROM AnTrua_members WHERE id = %s", (member_id,))
        member_name = cur.fetchone()[0]

        cur.execute("SELECT dish_name FROM AnTrua_meals WHERE id = %s", (meal_id,))
        meal_row = cur.fetchone()
        dish_name = meal_row[0] if meal_row else "Unknown"

        cur.execute("DELETE FROM AnTrua_payments WHERE id = %s", (payment_id,))

        cur.execute(
            "INSERT INTO AnTrua_logs (member_name, action, details, amount) VALUES (%s, %s, %s, %s)",
            (member_name, "payment_reverted", f"Hoan tac: {dish_name} - {amount:.0f} VND", amount),
        )

        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/payments")
def api_get_AnTrua_payments():
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    dish = request.args.get("dish", "").strip().lower()
    sort = request.args.get("sort", "desc")

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    sql = """
        SELECT p.id, p.member_id, p.meal_id, p.amount, p.created_at,
               mem.name as member_name, me.dish_name, me.date as meal_date
        FROM AnTrua_payments p
        JOIN AnTrua_members mem ON p.member_id = mem.id
        JOIN AnTrua_meals me ON p.meal_id = me.id
        WHERE 1=1
    """
    params = []

    if date_from:
        sql += " AND me.date >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND me.date <= %s"
        params.append(date_to)
    if dish:
        sql += " AND LOWER(me.dish_name) LIKE %s"
        params.append(f"%{dish}%")

    sql += f" ORDER BY p.created_at {sort.upper()}"
    sql += " LIMIT 200"

    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    AnTrua_payments = [
        {
            "id": str(row["id"]),
            "memberName": row["member_name"],
            "dishName": row["dish_name"],
            "date": row["meal_date"].isoformat() if row["meal_date"] else "",
            "amount": float(row["amount"]),
            "createdAt": row["created_at"].isoformat() if row["created_at"] else "",
        }
        for row in rows
    ]

    return jsonify(AnTrua_payments)


@app.route("/api/members/<name>/payments")
def api_member_payments(name):
    member_id = get_member_id(name)
    if not member_id:
        return jsonify({"success": False, "message": "Khong tim thay thanh vien"}), 404

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT p.id, p.amount, p.created_at, me.dish_name, me.date as meal_date
        FROM AnTrua_payments p
        JOIN AnTrua_meals me ON p.meal_id = me.id
        WHERE p.member_id = %s
        ORDER BY p.created_at DESC
        """,
        (member_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    payments = [
        {
            "id": str(row["id"]),
            "dishName": row["dish_name"],
            "date": row["meal_date"].isoformat() if row["meal_date"] else "",
            "amount": float(row["amount"]),
            "createdAt": row["created_at"].isoformat() if row["created_at"] else "",
        }
        for row in rows
    ]

    return jsonify({"success": True, "payments": payments})


@app.route("/api/logs")
def api_AnTrua_logs():
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    action = request.args.get("action", "").strip().lower()
    sort = request.args.get("sort", "desc")

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    sql = """
        SELECT member_name, action, details, amount, created_at
        FROM AnTrua_logs
        WHERE 1=1
    """
    params = []

    if date_from:
        sql += " AND DATE(created_at) >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND DATE(created_at) <= %s"
        params.append(date_to)
    if action:
        sql += " AND LOWER(action) LIKE %s"
        params.append(f"%{action}%")

    sql += f" ORDER BY created_at {sort.upper()}"
    sql += " LIMIT 200"

    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    AnTrua_logs = [
        {
            "memberName": row["member_name"],
            "action": row["action"],
            "details": row["details"],
            "amount": float(row["amount"]) if row["amount"] else 0,
            "createdAt": row["created_at"].isoformat() if row["created_at"] else "",
        }
        for row in rows
    ]

    return jsonify(AnTrua_logs)


# --- Member Management API ---

@app.route("/api/admin/members")
def api_admin_members():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT
            m.name,
            COALESCE(
                (SELECT SUM(me.per_person_cost)
                 FROM AnTrua_meal_participants mp
                 JOIN AnTrua_meals me ON mp.meal_id = me.id
                 WHERE mp.member_id = m.id AND mp.ate = TRUE), 0
            ) - COALESCE(
                (SELECT SUM(p.amount)
                 FROM AnTrua_payments p
                 WHERE p.member_id = m.id), 0
            ) as debt,
            (SELECT COUNT(*) FROM AnTrua_meal_participants mp WHERE mp.member_id = m.id AND mp.ate = TRUE) as meals_ate,
            (SELECT COUNT(*) FROM AnTrua_payments p WHERE p.member_id = m.id) as payments_count,
            m.created_at
        FROM AnTrua_members m
        ORDER BY debt DESC
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    members = [
        {
            "name": row["name"],
            "debt": float(row["debt"]),
            "mealsAte": row["meals_ate"],
            "paymentsCount": row["payments_count"],
            "createdAt": row["created_at"].isoformat() if row["created_at"] else "",
        }
        for row in rows
    ]

    return jsonify(members)


@app.route("/api/admin/members", methods=["POST"])
def api_admin_add_member():
    data = request.json
    name = data.get("name", "").strip()

    if not name:
        return jsonify({"success": False, "message": "Thieu ten"}), 400

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            "INSERT INTO AnTrua_members (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id",
            (name,),
        )
        row = cur.fetchone()
        if row:
            conn.commit()
            cur.close()
            conn.close()
            return jsonify({"success": True})
        else:
            cur.close()
            conn.close()
            return jsonify({"success": False, "message": "Thanh vien da ton tai"}), 409
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/admin/members/<name>", methods=["PUT"])
def api_admin_rename_member(name):
    data = request.json
    new_name = data.get("name", "").strip()

    if not new_name:
        return jsonify({"success": False, "message": "Thieu ten moi"}), 400

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            "UPDATE AnTrua_members SET name = %s WHERE name = %s",
            (new_name, name),
        )
        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return jsonify({"success": False, "message": "Khong tim thay thanh vien"}), 404

        cur.execute(
            "UPDATE AnTrua_logs SET member_name = %s WHERE member_name = %s",
            (new_name, name),
        )

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/admin/members/<name>", methods=["DELETE"])
def api_admin_delete_member(name):
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("SELECT id FROM AnTrua_members WHERE name = %s", (name,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return jsonify({"success": False, "message": "Khong tim thay thanh vien"}), 404

        cur.execute("DELETE FROM AnTrua_members WHERE name = %s", (name,))

        cur.execute(
            "INSERT INTO AnTrua_logs (member_name, action, details) VALUES (%s, %s, %s)",
            ("System", "member_deleted", f"Xoa thanh vien: {name}"),
        )

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/admin/dashboard")
def api_admin_dashboard():
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT COUNT(*) as count FROM AnTrua_meals")
    total_AnTrua_meals = cur.fetchone()["count"]

    cur.execute(
        """
        SELECT COALESCE(SUM(debt), 0) as total_debt FROM (
            SELECT
                COALESCE(
                    (SELECT SUM(me.per_person_cost)
                     FROM AnTrua_meal_participants mp
                     JOIN AnTrua_meals me ON mp.meal_id = me.id
                     WHERE mp.member_id = m.id AND mp.ate = TRUE), 0
                ) - COALESCE(
                    (SELECT SUM(p.amount)
                     FROM AnTrua_payments p
                     WHERE p.member_id = m.id), 0
                ) as debt
            FROM AnTrua_members m
        ) sub WHERE debt > 0
        """
    )
    total_debt = float(cur.fetchone()["total_debt"])

    cur.execute(
        """
        SELECT COALESCE(SUM(amount), 0) as total_paid
        FROM AnTrua_payments
        WHERE created_at >= date_trunc('month', CURRENT_DATE)
        """
    )
    total_paid = float(cur.fetchone()["total_paid"])

    cur.execute(
        """
        SELECT COALESCE(SUM(p.amount), 0) as duc_paid
        FROM AnTrua_payments p
        JOIN AnTrua_members m ON p.member_id = m.id
        WHERE m.name = 'Đức'
        """
    )
    duc_paid = float(cur.fetchone()["duc_paid"])

    cur.execute(
        "SELECT COUNT(DISTINCT member_id) as count FROM AnTrua_meal_participants WHERE ate = TRUE"
    )
    active_AnTrua_members = cur.fetchone()["count"]

    cur.execute(
        """
        SELECT member_name, action, details, amount, created_at
        FROM AnTrua_logs
        ORDER BY created_at DESC
        LIMIT 10
        """
    )
    recent = cur.fetchall()

    cur.close()
    conn.close()

    recent_transactions = [
        {
            "memberName": row["member_name"],
            "action": row["action"],
            "details": row["details"],
            "amount": float(row["amount"]) if row["amount"] else 0,
            "createdAt": row["created_at"].isoformat() if row["created_at"] else "",
        }
        for row in recent
    ]

    return jsonify(
        {
            "totalMeals": total_AnTrua_meals,
            "totalDebt": total_debt,
            "totalPaid": total_paid,
            "ducDebt": total_debt - duc_paid,
            "activeMembers": active_AnTrua_members,
            "recentTransactions": recent_transactions,
        }
    )


@app.route("/api/qr")
def api_qr():
    amount = request.args.get("amount", "0")
    description = request.args.get("description", "An trua BSV")

    bank_bin = VIETQR["bankBin"]
    account_no = VIETQR["accountNo"]
    template = VIETQR["template"]
    account_name = VIETQR["accountName"]

    qr_url = VIETQR["link_template"]
    qr_url = qr_url.replace("<BANK_ID>", bank_bin)
    qr_url = qr_url.replace("<ACCOUNT_NO>", account_no)
    qr_url = qr_url.replace("<TEMPLATE>", template)
    qr_url = qr_url.replace("<AMOUNT>", str(amount))
    qr_url = qr_url.replace("<DESCRIPTION>", description)
    qr_url = qr_url.replace("<ACCOUNT_NAME>", account_name)

    return jsonify({"qrUrl": qr_url})


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASS:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        else:
            return render_template("admin_login.html", error="Sai mat khau")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/admin")
def admin():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))
    return render_template("admin.html")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)