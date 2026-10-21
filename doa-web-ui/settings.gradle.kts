rootProject.name = "doa"

pluginManagement {
    val kotlinVersion: String by settings
    val protobufPluginVersion: String by settings
    plugins {
        kotlin("jvm") version kotlinVersion
        id("com.google.protobuf") version protobufPluginVersion
    }
    repositories {
        gradlePluginPortal()
    }
}