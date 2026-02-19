"""Calculator CLI entry point."""

from calculator import Calculator


def main() -> None:
    calc = Calculator()
    print(f"2 + 3 = {calc.add(2, 3)}")
    print(f"10 - 4 = {calc.subtract(10, 4)}")
    print(f"3 * 4 = {calc.multiply(3, 4)}")
    print(f"10 / 2 = {calc.divide(10, 2)}")


if __name__ == "__main__":
    main()
