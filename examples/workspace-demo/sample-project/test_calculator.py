"""Comprehensive tests for the Calculator class."""

import pytest
from calculator import Calculator


class TestCalculatorBasicOperations:
    """Tests for basic arithmetic operations with positive numbers."""

    def setup_method(self):
        """Create a Calculator instance for each test."""
        self.calc = Calculator()

    def test_add_two_positive_numbers(self):
        """Test adding two positive integers."""
        result = self.calc.add(5, 3)
        assert result == 8

    def test_add_positive_floats(self):
        """Test adding two positive floating-point numbers."""
        result = self.calc.add(2.5, 3.5)
        assert result == 6.0

    def test_subtract_smaller_from_larger(self):
        """Test subtracting a smaller number from a larger one."""
        result = self.calc.subtract(10, 4)
        assert result == 6

    def test_subtract_larger_from_smaller(self):
        """Test subtracting a larger number from a smaller one."""
        result = self.calc.subtract(3, 8)
        assert result == -5

    def test_multiply_two_positive_integers(self):
        """Test multiplying two positive integers."""
        result = self.calc.multiply(4, 5)
        assert result == 20

    def test_multiply_positive_floats(self):
        """Test multiplying two positive floating-point numbers."""
        result = self.calc.multiply(2.5, 4.0)
        assert result == 10.0

    def test_divide_evenly(self):
        """Test dividing two numbers that divide evenly."""
        result = self.calc.divide(20, 4)
        assert result == 5

    def test_divide_with_remainder(self):
        """Test dividing two numbers that result in a floating-point value."""
        result = self.calc.divide(10, 4)
        assert result == 2.5


class TestCalculatorNegativeNumbersAndZero:
    """Tests for operations involving negative numbers and zero."""

    def setup_method(self):
        """Create a Calculator instance for each test."""
        self.calc = Calculator()

    def test_add_negative_numbers(self):
        """Test adding two negative numbers."""
        result = self.calc.add(-5, -3)
        assert result == -8

    def test_add_positive_and_negative(self):
        """Test adding a positive and a negative number."""
        result = self.calc.add(10, -4)
        assert result == 6

    def test_add_zero(self):
        """Test adding zero to a number."""
        result = self.calc.add(7, 0)
        assert result == 7

    def test_subtract_negative_from_negative(self):
        """Test subtracting a negative number from another negative number."""
        result = self.calc.subtract(-5, -3)
        assert result == -2

    def test_subtract_negative_from_positive(self):
        """Test subtracting a negative number from a positive number."""
        result = self.calc.subtract(5, -3)
        assert result == 8

    def test_subtract_zero(self):
        """Test subtracting zero from a number."""
        result = self.calc.subtract(7, 0)
        assert result == 7

    def test_multiply_two_negative_numbers(self):
        """Test multiplying two negative numbers (result should be positive)."""
        result = self.calc.multiply(-4, -5)
        assert result == 20

    def test_multiply_positive_and_negative(self):
        """Test multiplying a positive and a negative number."""
        result = self.calc.multiply(4, -5)
        assert result == -20

    def test_multiply_by_zero(self):
        """Test multiplying any number by zero."""
        result = self.calc.multiply(100, 0)
        assert result == 0

    def test_multiply_negative_by_zero(self):
        """Test multiplying a negative number by zero."""
        result = self.calc.multiply(-50, 0)
        assert result == 0

    def test_divide_negative_by_negative(self):
        """Test dividing a negative number by another negative number."""
        result = self.calc.divide(-20, -4)
        assert result == 5

    def test_divide_positive_by_negative(self):
        """Test dividing a positive number by a negative number."""
        result = self.calc.divide(20, -4)
        assert result == -5

    def test_divide_negative_by_positive(self):
        """Test dividing a negative number by a positive number."""
        result = self.calc.divide(-20, 4)
        assert result == -5

    def test_divide_zero_by_number(self):
        """Test dividing zero by any non-zero number."""
        result = self.calc.divide(0, 5)
        assert result == 0


class TestCalculatorDivideByZero:
    """Tests for the divide-by-zero error case."""

    def setup_method(self):
        """Create a Calculator instance for each test."""
        self.calc = Calculator()

    def test_divide_by_zero_raises_value_error(self):
        """Test that dividing by zero raises a ValueError."""
        with pytest.raises(ValueError):
            self.calc.divide(10, 0)

    def test_divide_by_zero_error_message(self):
        """Test that the divide-by-zero error has the expected message."""
        with pytest.raises(ValueError, match="Cannot divide by zero"):
            self.calc.divide(10, 0)

    def test_divide_positive_by_zero_raises_error(self):
        """Test that dividing a positive number by zero raises ValueError."""
        with pytest.raises(ValueError):
            self.calc.divide(100, 0)

    def test_divide_negative_by_zero_raises_error(self):
        """Test that dividing a negative number by zero raises ValueError."""
        with pytest.raises(ValueError):
            self.calc.divide(-50, 0)

    def test_divide_zero_by_zero_raises_error(self):
        """Test that dividing zero by zero raises ValueError."""
        with pytest.raises(ValueError):
            self.calc.divide(0, 0)


class TestCalculatorLargeNumbersAndPrecision:
    """Tests for large numbers and floating-point precision."""

    def setup_method(self):
        """Create a Calculator instance for each test."""
        self.calc = Calculator()

    def test_add_large_numbers(self):
        """Test adding very large numbers."""
        result = self.calc.add(1_000_000_000, 2_000_000_000)
        assert result == 3_000_000_000

    def test_add_large_negative_numbers(self):
        """Test adding large negative numbers."""
        result = self.calc.add(-1_000_000_000, -2_000_000_000)
        assert result == -3_000_000_000

    def test_multiply_large_numbers(self):
        """Test multiplying large numbers."""
        result = self.calc.multiply(100_000, 100_000)
        assert result == 10_000_000_000

    def test_floating_point_addition_precision(self):
        """Test floating-point addition with decimal precision."""
        result = self.calc.add(0.1, 0.2)
        assert abs(result - 0.3) < 1e-10  # Allow for floating-point precision

    def test_floating_point_subtraction_precision(self):
        """Test floating-point subtraction with decimal precision."""
        result = self.calc.subtract(1.0, 0.9)
        assert abs(result - 0.1) < 1e-10  # Allow for floating-point precision

    def test_floating_point_multiplication_precision(self):
        """Test floating-point multiplication with decimal precision."""
        result = self.calc.multiply(0.1, 0.2)
        assert abs(result - 0.02) < 1e-10  # Allow for floating-point precision

    def test_floating_point_division_precision(self):
        """Test floating-point division with decimal precision."""
        result = self.calc.divide(1.0, 3.0)
        assert abs(result - 0.3333333333333333) < 1e-10  # Allow for floating-point precision

    def test_mixed_integer_and_float_operations(self):
        """Test operations mixing integers and floating-point numbers."""
        result = self.calc.add(5, 3.5)
        assert result == 8.5

        result = self.calc.multiply(4, 2.5)
        assert result == 10.0

    def test_very_small_numbers(self):
        """Test operations with very small (close to zero) numbers."""
        result = self.calc.add(1e-10, 1e-10)
        assert abs(result - 2e-10) < 1e-20

    def test_chained_operations(self):
        """Test that results can be used in subsequent operations."""
        intermediate = self.calc.add(5, 3)
        result = self.calc.multiply(intermediate, 2)
        assert result == 16
