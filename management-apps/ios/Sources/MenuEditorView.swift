import SwiftUI

struct MenuEditorView: View {
    @ObservedObject var model: ManagementModel
    let menu: ManagementMenu
    @State private var categoryName = ""

    var body: some View {
        List {
            Section("management.addCategory") {
                TextField("management.categoryName", text: $categoryName)
                    .textInputAutocapitalization(.words)
                Button("management.addCategory") {
                    let name = categoryName.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !name.isEmpty else { return }
                    Task {
                        await model.createCategory(menuID: menu.id, name: name)
                        if model.errorMessage == nil {
                            categoryName = ""
                        }
                    }
                }
                .disabled(categoryName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isLoading)
            }

            Section("management.categories") {
                if model.isLoading && model.menuContent == nil {
                    ProgressView("management.loading")
                } else if let content = model.menuContent {
                    if content.categories.isEmpty {
                        Text("management.emptyCategories")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(content.categories) { category in
                        NavigationLink {
                            CategoryEditorView(model: model, menu: menu, categoryID: category.id)
                        } label: {
                            HStack {
                                Text(category.name)
                                Spacer()
                                Text(category.dishes.count.formatted())
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle(menu.name)
        .task { await model.loadMenuContent(menuID: menu.id) }
        .refreshable { await model.loadMenuContent(menuID: menu.id) }
    }
}

private struct CategoryEditorView: View {
    @ObservedObject var model: ManagementModel
    let menu: ManagementMenu
    let categoryID: Int
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var didLoadName = false
    @State private var isConfirmingDelete = false

    private var category: ManagementCategory? {
        model.menuContent?.categories.first { $0.id == categoryID }
    }

    var body: some View {
        Form {
            Section("management.category") {
                TextField("management.categoryName", text: $name)
                    .textInputAutocapitalization(.words)
                Button("management.saveCategory") {
                    Task {
                        await model.updateCategory(
                            menuID: menu.id,
                            categoryID: categoryID,
                            name: name.trimmingCharacters(in: .whitespacesAndNewlines)
                        )
                        if model.errorMessage == nil {
                            dismiss()
                        }
                    }
                }
                .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isLoading)
                Button("management.deleteCategory", role: .destructive) {
                    isConfirmingDelete = true
                }
                .disabled(model.isLoading)
            }

            Section("management.dishes") {
                if let category {
                    ForEach(category.dishes) { dish in
                        NavigationLink {
                            DishEditorView(
                                model: model,
                                menu: menu,
                                categoryID: categoryID,
                                dishID: dish.id
                            )
                        } label: {
                            VStack(alignment: .leading) {
                                Text(dish.name)
                                if let price = dish.price {
                                    Text("\(price) \(String(localized: "management.currency"))")
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
                NavigationLink("management.addDish") {
                    DishEditorView(model: model, menu: menu, categoryID: categoryID)
                }
            }
        }
        .navigationTitle(category?.name ?? String(localized: "management.category"))
        .task {
            guard !didLoadName, let category else { return }
            name = category.name
            didLoadName = true
        }
        .confirmationDialog(
            "management.deleteCategoryConfirmation",
            isPresented: $isConfirmingDelete,
            titleVisibility: .visible
        ) {
            Button("management.deleteCategory", role: .destructive) {
                Task {
                    await model.deleteCategory(menuID: menu.id, categoryID: categoryID)
                    if model.errorMessage == nil {
                        dismiss()
                    }
                }
            }
        }
    }
}

private struct DishEditorView: View {
    @ObservedObject var model: ManagementModel
    let menu: ManagementMenu
    let categoryID: Int
    let dishID: Int?
    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var description: String
    @State private var price: String
    @State private var isVisible: Bool
    @State private var isConfirmingDelete = false

    private var dish: ManagementDish? {
        guard let dishID, let categories = model.menuContent?.categories else { return nil }
        return categories.flatMap { $0.dishes }.first { $0.id == dishID }
    }

    init(model: ManagementModel, menu: ManagementMenu, categoryID: Int, dishID: Int? = nil) {
        self.model = model
        self.menu = menu
        self.categoryID = categoryID
        self.dishID = dishID
        let dishes = (model.menuContent?.categories ?? []).flatMap { $0.dishes }
        let dish = dishID.flatMap { id in dishes.first { $0.id == id } }
        _name = State(initialValue: dish?.name ?? "")
        _description = State(initialValue: dish?.description ?? "")
        _price = State(initialValue: dish?.price ?? "")
        _isVisible = State(initialValue: dish?.isVisible ?? true)
    }

    var body: some View {
        Form {
            Section("management.dish") {
                TextField("management.dishName", text: $name)
                    .textInputAutocapitalization(.words)
                TextField("management.dishDescription", text: $description, axis: .vertical)
                    .lineLimit(2...5)
                TextField("management.dishPrice", text: $price)
                    .keyboardType(.decimalPad)
                Toggle("management.dishVisible", isOn: $isVisible)
            }

            Section {
                Button(dishID == nil ? "management.addDish" : "management.saveDish") {
                    Task {
                        if let dishID, let dish {
                            await model.updateDish(
                                menuID: menu.id,
                                dishID: dishID,
                                name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                                description: description,
                                price: price,
                                isVisible: isVisible,
                                allergens: dish.allergens
                            )
                        } else {
                            await model.createDish(
                                menuID: menu.id,
                                categoryID: categoryID,
                                name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                                description: description,
                                price: price,
                                isVisible: isVisible
                            )
                        }
                        if model.errorMessage == nil {
                            dismiss()
                        }
                    }
                }
                .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isLoading)

                if let dishID {
                    Button("management.deleteDish", role: .destructive) {
                        isConfirmingDelete = true
                    }
                    .disabled(model.isLoading)
                }
            }
        }
        .navigationTitle(dish == nil ? String(localized: "management.addDish") : String(localized: "management.editDish"))
        .confirmationDialog(
            "management.deleteDishConfirmation",
            isPresented: $isConfirmingDelete,
            titleVisibility: .visible
        ) {
            if let dishID {
                Button("management.deleteDish", role: .destructive) {
                    Task {
                        await model.deleteDish(menuID: menu.id, dishID: dishID)
                        if model.errorMessage == nil {
                            dismiss()
                        }
                    }
                }
            }
        }
    }
}
