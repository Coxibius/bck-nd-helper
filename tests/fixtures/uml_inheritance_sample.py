
"""Small inheritance example retained as fixture data, not a pytest case."""


class Animal:
    def __init__(self, name):
        self.name = name

    def speak(self):
        pass

class Dog(Animal):
    def bark(self):
        print("Woof")

class Cat(Animal):
    def meow(self):
        print("Meow")
