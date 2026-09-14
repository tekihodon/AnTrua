package main

import (
	"context"
	"database/sql"
	"fmt"
	"net/http"
	"os"
	"time"

	"github.com/gin-gonic/gin"
	_ "github.com/lib/pq"
)

// Member represents a member in the system
type Member struct {
	Name          string  `json:"name"`
	Debt          float64 `json:"debt"`
	MealsAte      int     `json:"mealsAte"`
	PaymentsCount int     `json:"paymentsCount"`
	CreatedAt     string  `json:"createdAt"`
}

// Meal represents a meal record
type Meal struct {
	ID            string   `json:"id"`
	Date          string   `json:"date"`
	DishName      string   `json:"dishName"`
	TotalCost     float64  `json:"totalCost"`
	PerPersonCost float64  `json:"perPersonCost"`
	Participants  []string `json:"participants"`
	CreatedAt     string   `json:"createdAt"`
}

// Payment represents a payment record
type Payment struct {
	ID         string  `json:"id"`
	MemberID   string  `json:"memberId"`
	MealID     string  `json:"mealId"`
	MemberName string  `json:"memberName"`
	DishName   string  `json:"dishName"`
	Date       string  `json:"date"`
	Amount     float64 `json:"amount"`
	CreatedAt  string  `json:"createdAt"`
}

// Log represents a log record
type Log struct {
	MemberName string  `json:"memberName"`
	Action     string  `json:"action"`
	Details    string  `json:"details"`
	Amount     float64 `json:"amount"`
	CreatedAt  string  `json:"createdAt"`
}

// App holds the database connection and other shared state
type App struct {
	DB *sql.DB
}

// NewApp creates a new Application with a PostgreSQL database
func NewApp() (*App, error) {
	connStr := os.Getenv("DATABASE_URL")
	if connStr == "" {
		fmt.Println("WARNING: DATABASE_URL environment variable is not set. Server will start but database operations will fail until configured.")
		return &App{DB: nil}, nil
	}

	db, err := sql.Open("postgres", connStr)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to connect to database: %w", err)
	}

	fmt.Println("Successfully connected to database")
	return &App{DB: db}, nil
}

// getMemberID retrieves a member ID by name from the database
func (a *App) getMemberID(name string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	sql := `SELECT id FROM AnTrua_members WHERE name = $1`
	var memberID string
	if err := a.DB.QueryRowContext(ctx, sql, name).Scan(&memberID); err != nil {
		return "", err
	}
	return memberID, nil
}

// ensureMember ensures a member exists in the database
func (a *App) ensureMember(name string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	_, err := a.DB.ExecContext(ctx, `
		INSERT INTO AnTrua_members (name) VALUES ($1) ON CONFLICT (name) DO NOTHING
	`, name)
	if err != nil {
		return fmt.Errorf("failed to ensure member %s: %w", name, err)
	}
	return nil
}

// getMembers returns all members sorted by debt (most indebted first)
func (a *App) getMembers() ([]Member, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	sql := `
		SELECT m.name,
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
		       (SELECT COUNT(*) FROM AnTrua_meal_participants mp WHERE mp.member_id = m.id AND mp.ate = TRUE) as mealsAte,
		       (SELECT COUNT(*) FROM AnTrua_payments p WHERE p.member_id = m.id) as paymentsCount,
		       m.created_at
		FROM AnTrua_members m
		ORDER BY debt DESC
	`
	
	rows, err := a.DB.QueryContext(ctx, sql)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var members []Member
	for rows.Next() {
		var member Member
		var createdAt time.Time
		if err := rows.Scan(&member.Name, &member.Debt, &member.MealsAte, &member.PaymentsCount, &createdAt); err != nil {
			return nil, err
		}
		member.CreatedAt = createdAt.Format(time.RFC3339)
		members = append(members, member)
	}
	return members, nil
}

// addMeal creates a new meal record
func (a *App) addMeal(dateStr, dishName string, totalCost float64, participants []string) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	mealDate, err := time.Parse("2006-01-02", dateStr)
	if err != nil {
		return "", fmt.Errorf("invalid date format: %s", dateStr)
	}

	tx, err := a.DB.BeginTx(ctx, nil)
	if err != nil {
		return "", fmt.Errorf("failed to start transaction: %w", err)
	}
	defer tx.Rollback()

	perPersonCost := totalCost / float64(len(participants))

	var mealID string
	err = tx.QueryRowContext(ctx, `
		INSERT INTO AnTrua_meals (date, dish_name, total_cost, per_person_cost) VALUES ($1, $2, $3, $4) RETURNING id
	`, mealDate, dishName, totalCost, perPersonCost).Scan(&mealID)
	if err != nil {
		return "", fmt.Errorf("failed to insert meal: %w", err)
	}

	for _, p := range participants {
		if err := a.ensureMember(p); err != nil {
			return "", err
		}
		memberID, err := a.getMemberID(p)
		if err != nil {
			return "", err
		}
		_, err = tx.ExecContext(ctx, `
			INSERT INTO AnTrua_meal_participants (meal_id, member_id, ate) VALUES ($1, $2, TRUE)
		`, mealID, memberID)
		if err != nil {
			return "", fmt.Errorf("failed to add participant %s to meal %s: %w", p, mealID, err)
		}
	}

	_, err = tx.ExecContext(ctx, `
		INSERT INTO AnTrua_logs (member_name, action, details, amount) VALUES ($1, $2, $3, $4)
	`, "System", "bill_added", fmt.Sprintf("Them hoa don: %s - %.0f VND", dishName, totalCost), totalCost)
	if err != nil {
		return "", fmt.Errorf("failed to log payment: %w", err)
	}

	if err := tx.Commit(); err != nil {
		return "", fmt.Errorf("failed to commit transaction: %w", err)
	}

	return mealID, nil
}

// deleteMeal removes a meal record
func (a *App) deleteMeal(mealID string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	_, err := a.DB.ExecContext(ctx, `DELETE FROM AnTrua_meals WHERE id = $1`, mealID)
	if err != nil {
		return fmt.Errorf("failed to delete meal: %w", err)
	}
	return nil
}

// getMeals returns all meals with participant details
func (a *App) getMeals() ([]Meal, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	sql := `
		SELECT m.id, m.date, m.dish_name, m.total_cost, m.per_person_cost, m.created_at
		FROM AnTrua_meals m
		ORDER BY m.date DESC, m.created_at DESC
	`
	rows, err := a.DB.QueryContext(ctx, sql)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var meals []Meal
	for rows.Next() {
		var meal Meal
		var date time.Time
		var createdAt time.Time

		if err := rows.Scan(&meal.ID, &date, &meal.DishName, &meal.TotalCost, &meal.PerPersonCost, &createdAt); err != nil {
			return nil, err
		}

		participants, err := a.getMealParticipants(meal.ID)
		if err != nil {
			return nil, err
		}

		meal.Date = date.Format("2006-01-02")
		meal.CreatedAt = createdAt.Format(time.RFC3339)
		meal.Participants = participants
		meals = append(meals, meal)
	}

	return meals, nil
}

func (a *App) getMealParticipants(mealID string) ([]string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	sql := `
		SELECT mem.name FROM AnTrua_meal_participants mp
		JOIN AnTrua_members mem ON mp.member_id = mem.id
		WHERE mp.meal_id = $1 AND mp.ate = TRUE
	`
	rows, err := a.DB.QueryContext(ctx, sql, mealID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var participants []string
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err != nil {
			return nil, err
		}
		participants = append(participants, name)
	}
	return participants, nil
}

// getPayments returns all payments
func (a *App) getPayments() ([]Payment, error) {
	if a.DB == nil {
		return nil, fmt.Errorf("database not configured")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	sql := `
		SELECT p.id, p.member_id, p.meal_id, p.amount, p.created_at,
		       mem.name as member_name, me.dish_name, me.date as meal_date
		FROM AnTrua_payments p
		JOIN AnTrua_members mem ON p.member_id = mem.id
		JOIN AnTrua_meals me ON p.meal_id = me.id
		ORDER BY p.created_at DESC
	`
	rows, err := a.DB.QueryContext(ctx, sql)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var payments []Payment
	for rows.Next() {
		var payment Payment
		var mealDate time.Time
		var createdAt time.Time

		if err := rows.Scan(&payment.ID, &payment.MemberID, &payment.MealID, &payment.Amount, &createdAt, &payment.MemberName, &payment.DishName, &mealDate); err != nil {
			return nil, err
		}

		payment.Date = mealDate.Format("2006-01-02")
		payment.CreatedAt = createdAt.Format(time.RFC3339)
		payments = append(payments, payment)
	}

	return payments, nil
}

// main initializes the application and starts the HTTP server
func main() {
	app, err := NewApp()
	if err != nil {
		fmt.Println("Failed to initialize app:", err)
		os.Exit(1)
	}
	if app.DB != nil {
		defer app.DB.Close()
	}

	// Setup routes
	router := gin.New()
	router.GET("/", func(c *gin.Context) {
		c.JSON(200, gin.H{"message": "AnTrua Go Backend"})
	})

	router.GET("/api/members", func(c *gin.Context) {
		if app.DB == nil {
			c.JSON(503, gin.H{"error": "Database not configured. Set DATABASE_URL environment variable."})
			return
		}
		members, err := app.getMembers()
		if err != nil {
			c.JSON(500, gin.H{"error": "Failed to fetch members"})
			return
		}
		c.JSON(200, members)
	})

	router.GET("/api/members/:name/debt-details", func(c *gin.Context) {
		if app.DB == nil {
			c.JSON(503, gin.H{"error": "Database not configured. Set DATABASE_URL environment variable."})
			return
		}
		name := c.Param("name")
		memberID, err := app.getMemberID(name)
		if err != nil {
			c.JSON(404, gin.H{"error": "Member not found"})
			return
		}
		c.JSON(200, gin.H{"memberID": memberID})
	})

	router.POST("/api/meals", func(c *gin.Context) {
		if app.DB == nil {
			c.JSON(503, gin.H{"error": "Database not configured. Set DATABASE_URL environment variable."})
			return
		}
		var data map[string]interface{}
		if err := c.ShouldBindJSON(&data); err != nil {
			c.JSON(400, gin.H{"error": "Invalid JSON"})
			return
		}

		dateStr := data["date"]
		dishName := data["dishName"]
		totalCost := data["totalCost"]
		participants := data["participants"]

		if dateStr == nil || dishName == nil || totalCost == nil || participants == nil {
			c.JSON(400, gin.H{"error": "Missing required fields"})
			return
		}

		dateStrStr, ok := dateStr.(string)
		if !ok {
			c.JSON(400, gin.H{"error": "Invalid date"})
			return
		}

		dishNameStr, ok := dishName.(string)
		if !ok {
			c.JSON(400, gin.H{"error": "Invalid dish name"})
			return
		}

		totalCostFloat, ok := totalCost.(float64)
		if !ok {
			c.JSON(400, gin.H{"error": "Invalid total cost"})
			return
		}

		participantsArr, ok := participants.([]interface{})
		if !ok {
			c.JSON(400, gin.H{"error": "Invalid participants"})
			return
		}

		participantNames := make([]string, len(participantsArr))
		for i, p := range participantsArr {
			name, ok := p.(string)
			if !ok {
				c.JSON(400, gin.H{"error": "Invalid participant"})
				return
			}
			participantNames[i] = name
		}

		mealID, err := app.addMeal(dateStrStr, dishNameStr, totalCostFloat, participantNames)
		if err != nil {
			c.JSON(500, gin.H{"error": "Failed to add meal"})
			return
		}

		c.JSON(201, gin.H{"success": true, "mealId": mealID})
	})

	router.GET("/api/meals", func(c *gin.Context) {
		if app.DB == nil {
			c.JSON(503, gin.H{"error": "Database not configured. Set DATABASE_URL environment variable."})
			return
		}
		meals, err := app.getMeals()
		if err != nil {
			c.JSON(500, gin.H{"error": "Failed to fetch meals"})
			return
		}
		c.JSON(200, meals)
	})

	router.GET("/api/meals/:id", func(c *gin.Context) {
		if app.DB == nil {
			c.JSON(503, gin.H{"error": "Database not configured. Set DATABASE_URL environment variable."})
			return
		}
		id := c.Param("id")
		if err := app.deleteMeal(id); err != nil {
			c.JSON(404, gin.H{"error": "Meal not found"})
			return
		}
		c.JSON(200, gin.H{"success": true})
	})

	router.GET("/api/payments", func(c *gin.Context) {
		if app.DB == nil {
			c.JSON(503, gin.H{"error": "Database not configured. Set DATABASE_URL environment variable."})
			return
		}
		payments, err := app.getPayments()
		if err != nil {
			c.JSON(500, gin.H{"error": "Failed to fetch payments"})
			return
		}
		c.JSON(200, payments)
	})

	router.GET("/api/logs", func(c *gin.Context) {
		if app.DB == nil {
			c.JSON(503, gin.H{"error": "Database not configured. Set DATABASE_URL environment variable."})
			return
		}
		c.JSON(200, gin.H{"message": "Logs endpoint"})
	})

	router.GET("/admin", func(c *gin.Context) {
		c.JSON(200, gin.H{"message": "Admin dashboard"})
	})

	// Start server
	addr := ":5000"
	if err := http.ListenAndServe(addr, router); err != nil {
		fmt.Println("Server failed:", err)
		os.Exit(1)
	}
	fmt.Println("AnTrua Go Backend starting on port 5000")
}
